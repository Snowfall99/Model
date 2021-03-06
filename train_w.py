import path2data_w
from typing import Union, Tuple
import torch
from torch_geometric.data import Data, DataLoader
from torch_geometric.nn import MessagePassing, TopKPooling, GraphConv
import torch_geometric.nn
from torch_geometric.utils import add_self_loops, degree
from torch.nn import Sequential as Seq, Linear, ReLU, Sigmoid
import torch.nn.functional as F
import random
import numpy as np
from torch_geometric.nn import global_mean_pool as gap, global_max_pool as gmp
import time

startTime = time.time()

good_label = 0
bad_label = 0


datapath = r"/home/chenzx/testcases/CWE121_Stack_Based_Buffer_Overflow"


dataset = path2data_w.loadPath2DataSet(datapath)

random.shuffle(dataset)
lenDataset = len(dataset)
lenTrainset = int(0.7*lenDataset)
lenValidset = int(0.2*lenDataset)
lenTestset = lenDataset - lenTrainset - lenValidset
print("数据集总量：%d 训练集：%d 验证集：%d 测试集：%d" % (lenDataset, lenTrainset, lenValidset, lenTestset))
trainSet = dataset[:lenTrainset]
for data in trainSet:
    if data["y"] == 1:
        good_label += 1
    elif data["y"] == 0:
        bad_label += 1
print("good_label: %d bad_label: %d" % (good_label, bad_label))
# 验证集
validateSet = dataset[lenTrainset:lenTrainset+lenValidset]
# 测试集
testSet = dataset[lenTrainset+lenValidset:]
# 加载训练集
trainloader = DataLoader(dataset=trainSet,batch_size=32,shuffle=True)
testloader = DataLoader(dataset=testSet, batch_size=32, shuffle=True)

finishDataLoadingTime = time.time()

# GCN Layer
class GCNConv(MessagePassing):
    def __init__(self, in_channels, out_channels, aggr='add', **kwargs):
        # 聚集方案：add
        super(GCNConv, self).__init__(aggr=aggr, **kwargs)

        self.in_channels = in_channels
        self.out_channels = out_channels

        self.lin = torch.nn.Linear(in_channels, out_channels)

    def forward(self, x, edge_index):
        # x has shape [N, in_channels]
        # edge_index has shape [2, E]
        # x, edge_index = data.x, data.edge_index

        # Step 1: Add self-loops to the adjacency matrix.
        edge_index, _ = add_self_loops(edge_index, num_nodes=x.size(0))

        # Step 2: Linearly transform node feature matrix.
        x = self.lin(x)

        # Step 3: Compute normalization
        row, col = edge_index
        deg = degree(row, x.size(0), dtype=x.dtype)
        deg_inv_sqrt = deg.pow(-0.5)
        norm = deg_inv_sqrt[row] * deg_inv_sqrt[col]

        # Step 4-6: Start propagating messages.
        return self.propagate(edge_index, size=(x.size(0), x.size(0)), x=x,
                              norm=norm)

    def message(self, x_j, norm):
        # x_j has shape [E, out_channels]

        # Step 4: Normalize node features.
        return norm.view(-1, 1) * x_j

    def update(self, aggr_out):
        # aggr_out has shape [N, out_channels]
        # Step 6: Return new node embeddings.
        return aggr_out

class Net(torch.nn.Module):
    def __init__(self):
        super(Net, self).__init__()

        self.conv1 = GCNConv(128, 128)
        #self.conv1 = GraphConv(256, 128)
        self.pool1 = TopKPooling(128, ratio=0.8)
        self.conv2 = GCNConv(128, 128)
        #self.conv2 = GraphConv(256, 128)
        self.pool2 = TopKPooling(128, ratio=0.8)
        self.conv3 = GCNConv(128, 128)
        #self.conv3 = GraphConv(256, 128)
        self.pool3 = TopKPooling(128, ratio=0.8)

        self.conv4 = GCNConv(128, 128)
        self.pool4 = TopKPooling(128, ratio=0.8)
        self.conv5 = GCNConv(128, 128)
        self.pool5 = TopKPooling(128, ratio=0.8)

        self.lin1 = torch.nn.Linear(256, 128)
        self.lin2 = torch.nn.Linear(128, 64)
        self.lin3 = torch.nn.Linear(64, 2)

        self.readout = Seq(Linear(128, 64),
                           ReLU(),
                           Linear(64, 2))

    def forward(self, x, edge_index, batch):
        # x, edge_index, batch = data.x, data.edge_index, data.batch

        x = F.relu(self.conv1(x, edge_index))
        x, edge_index, _, batch, _, _ = self.pool1(x, edge_index, None, batch)
        x1 = torch.cat([gmp(x, batch), gap(x, batch)], dim=1)

        x = F.relu(self.conv2(x, edge_index))
        x, edge_index, _, batch, _, _ = self.pool2(x, edge_index, None, batch)
        x2 = torch.cat([gmp(x, batch), gap(x, batch)], dim=1)

        x = F.relu(self.conv3(x, edge_index))
        x, edge_index, _, batch, _, _ = self.pool3(x, edge_index, None, batch)
        x3 = torch.cat([gmp(x, batch), gap(x, batch)], dim=1)

        x = F.relu(self.conv4(x, edge_index))
        x, edge_index, _, batch, _, _ = self.pool4(x, edge_index, None, batch)
        x4 = torch.cat([gmp(x, batch), gap(x, batch)], dim=1)

        x = F.relu(self.conv5(x, edge_index))
        x, edge_index, _, batch, _, _ = self.pool5(x, edge_index, None, batch)
        x5 = torch.cat([gmp(x, batch), gap(x, batch)], dim=1)

        x = x1 + x2 + x3 + x4 + x5

        x = F.relu(self.lin1(x))
        x = F.dropout(x, p=0.5, training=self.training)
        x = F.relu(self.lin2(x))
        x = F.log_softmax(self.lin3(x), dim=-1)

        return x




device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model = Net().to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
criterion = torch.nn.CrossEntropyLoss()

def train(epoch):
    model.train()

    loss_all = 0
    for data in trainloader:
        data = data.to(device)
        optimizer.zero_grad()
        x, edge_index, batch = data.x, data.edge_index, data.batch
        output = model(x, edge_index, batch)
        loss = F.nll_loss(output, data.y)
        loss.backward()
        loss_all += data.num_graphs * loss.item()
        optimizer.step()
    return loss_all / len(trainSet)

def myTest(loader):
    model.eval()
    A_Num = 0
    B_Num = 0
    correct = 0
    for data in loader:
        data = data.to(device)
        x, edge_index, batch = data.x, data.edge_index, data.batch
        pred = model(x, edge_index, batch).max(dim=1)[1]
        A = torch.tensor([1], dtype=torch.long)
        B = torch.tensor([0], dtype=torch.long)
        if torch.equal(pred, A):
            A_Num = A_Num + 1
        if torch.equal(pred, B):
            B_Num = B_Num + 1
        correct += pred.eq(data.y).sum().item()
    return correct / len(loader.dataset),A_Num,B_Num

f = open(r"/home/chenzx/train/C121.txt", "a")
for epoch in range(1, 5001):
    loss = train(epoch)
    train_acc ,TrainNum1,TrainNum2= myTest(trainloader)
    test_acc ,TestNum1 ,TestNum2 = myTest(testloader)
    print('Epoch: {:03d}, Loss: {:.5f}, Train Acc: {:.5f},Test Acc: {:.5f}'.
          format(epoch, loss, train_acc, test_acc ))


    f.write("Epoch: "+ str(epoch) +","+"Loss: "+str(loss)+","+"Train acc: "+str(train_acc)+","+"Test acc"+str(test_acc) + "\n")


finishTime = time.time()

# model.eval()
# testSet = [data.to(device) for data in testSet]
# testNumber = len(testSet)
# tp = 0
# tn = 0
# fp = 0
# fn = 0
# for test in testloader:
#     test = test.to(device)
#     x, edge_index, batch = test.x, test.edge_index, test.batch
#     res = model(test)
#     _, pred = res.max(dim=1)
#     if pred == 1 and test.y == 1:
#         tp += 1
#     elif pred == 0 and test.y == 0:
#         tn += 1
#     elif pred == 1 and test.y == 0:
#         fp += 1
#     elif pred == 0 and test.y == 1:
#         fn += 1
# accuracy = (tp+tn) / (tp+tn+fp+fn)
# print('Accuracy: {:.4f}'.format(accuracy))
# try:
#     precision = tp/(tp+fp)
#     recall = tp/(tp+fn)
#     f1 = (2*precision*recall)/(precision+recall)
#     print('Precision: {:.4f}'.format(precision))
#     print('Recall: {:.4f}'.format(recall))
#     print('F1: {:.4f}'.format(f1))
#     print("tp:", tp, "tn:", tn)
#     print("fp:", fp, "fn:", fn)
# except:
#     print("tp:",tp,"tn:",tn)
#     print("fp:",fp,"fn:",fn)

print("dataloading time: ", finishDataLoadingTime-startTime)
f.write("dataloading time: "+str(finishDataLoadingTime-startTim)+"\n")
print("training and testing time: ", finishTime-finishDataLoadingTime)
f.write("training and testing time: "+str(finishTime-finishDataLoadingTime)+"\n")
f.close()