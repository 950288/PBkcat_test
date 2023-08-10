import torch
import torch.nn as nn
import pickle
import random
import numpy as np
import torch.optim as optim
import torch.nn.functional as F
from sklearn.metrics import mean_squared_error,r2_score
import tqdm
from torch.optim.lr_scheduler import MultiStepLR

num_filters = 32
kernel_size = 3

"""The model of Kcat prediction."""
class KcatPrediction(nn.Module):
    def __init__(self, args, device):
        super().__init__()
        self.device = device
        self.dim: int = args['dim']
        self.layer_output: int = args['layer_output']
        self.layer_gnn: int = args['layer_gnn']
        self.lr = args['lr']
        self.len_fingerprint: int = args['len_fingerprint']
        self.weight_decay = args['weight_decay']

        """The embedding layer of compound fingerprint."""
        self.embed_fingerprint = nn.Embedding(self.len_fingerprint, self.dim)
        """The GNN layers."""
        self.W_gnn = nn.ModuleList([
            nn.Linear(self.dim, self.dim)
            for _ in range(self.layer_gnn)
        ])
        """The CNN layers."""
        self.conv_layers = nn.ModuleList([
            nn.Conv2d(in_channels=1, out_channels=num_filters, kernel_size=(kernel_size, 26)),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.Conv2d(in_channels=num_filters, out_channels=num_filters*2, kernel_size=(kernel_size, 1)),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=(2, 1))
        ])
        """The FC layers."""
        self.fc_layers = nn.ModuleList([
            nn.Linear(59328, 512),
            nn.ReLU(),
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, self.dim)
        ])
        """The output layers."""
        self.W_out = nn.ModuleList([
            nn.Linear(2*self.dim, 2*self.dim)                        
            for _ in range(self.layer_output)
        ])
        """The output layer to predict the interaction."""
        self.W_interaction = nn.Linear(2*self.dim, 1)

    """The GNN layer."""
    def gnn(self, xs, A, layer):
        for i in range(layer):
            hs = torch.relu(self.W_gnn[i](xs))
            xs = xs + torch.matmul(A.float(), hs)
        return torch.unsqueeze(torch.mean(xs, 0), 0)
    
    """The attention mechanism is applied."""
    def attention(self, compound_vector, protein_flatten):
        """The attention mechanism is applied."""
        weights = torch.tanh(F.linear(compound_vector, protein_flatten))
        ys = torch.t(weights) * protein_flatten
        return torch.unsqueeze(torch.mean(ys, 0), 0)
    
    def forward(self, inputs):
        fingerprints, adjacency, protein = inputs
        fingerprints = torch.LongTensor(fingerprints).to(self.device)
        adjacency = torch.FloatTensor(adjacency).to(self.device)
        protein = torch.FloatTensor(protein).to(self.device)

        """Compound vector with GNN."""
        fingerprint_vectors = self.embed_fingerprint(fingerprints)
        compound_vector = self.gnn(fingerprint_vectors, adjacency, self.layer_gnn)

        """Protein vector with CNN."""
        protein = protein.unsqueeze(0)
        """The protein vector is reshaped to fit the input of CNN."""
        for layer in self.conv_layers:
            protein = layer(protein)
        protein = protein.view(protein.size(0), -1)

        """Protein vector with FC."""
        protein_flatten = torch.flatten(protein)
        for layer in self.fc_layers:
            protein_flatten = layer(protein_flatten)
        protein_flatten = protein_flatten.unsqueeze(0)

        """The attention mechanism is applied."""
        protein_attention = self.attention(compound_vector, protein_flatten)

        """Concatenate the two vector and output the interaction."""
        cat_vector = torch.cat((compound_vector, protein_attention), 1)
        """The output layers for interaction prediction."""
        for j in range(self.layer_output):
            cat_vector = torch.relu(self.W_out[j](cat_vector))
        interaction = self.W_interaction(cat_vector)
        return interaction

"""Load the data."""
def load_pickle(file_name):
    with open(file_name, 'rb') as f:
        return pickle.load(f)

"""Split the dataset into train, dev and test set."""
def split_dataset(dataset, ratio):
    n = int(ratio * len(dataset))
    dataset_1, dataset_2 = dataset[:n], dataset[n:]
    return dataset_1, dataset_2

"""The trainer of the model."""
class Trainer(object):
    def __init__(self, model):
        self.model = model
        self.optimizer = optim.Adam(self.model.parameters(),
            lr=model.lr, weight_decay=model.weight_decay)
        """The learning rate decay scheduler."""
        self.scheduler1 = MultiStepLR(self.optimizer,[35,70] , gamma=0.1, last_epoch=-1, verbose=False)

    def train(self, dataset):
        loss_total, trainCorrect, trainPredict = 0, [], [] 
        random.shuffle(dataset)
        self.model.train()
        for data in tqdm.tqdm(dataset):
            self.optimizer.zero_grad()
            predicted = self.model(data[:3])
            loss = F.mse_loss(predicted[0][0].to(torch.float32), data[3].to(torch.float32).to(self.model.device))
            loss_total += loss.item()
            loss.backward()
            self.optimizer.step()
            trainCorrect.append(data[3].to(torch.float32))
            trainPredict.append(predicted[0][0].to(torch.float32))

        """The learning rate decay scheduler."""
        self.scheduler1.step()
        trainCorrect = torch.stack(trainCorrect).detach().cpu().numpy()
        trainPredict = torch.stack(trainPredict).detach().cpu().numpy()
        rmse_train = np.sqrt(mean_squared_error(trainCorrect, trainPredict))
        r2_train = r2_score(trainCorrect, trainPredict)
        print('Train RMSE: %.4f , R2: %.4f , LR: %.6f' %(rmse_train, r2_train, self.scheduler1.get_last_lr()[0]))
        # torch.cuda.empty_cache()
        return loss_total, rmse_train, r2_train,  self.scheduler1.get_last_lr()

"""The tester of the model."""
class Tester(object):
    def __init__(self, model):
        self.model = model

    def test(self, dataset):
        loss_total, testCorrect, testPredict = 0, [], [] 
        self.model.eval()
        for data in tqdm.tqdm(dataset):
            predicted = self.model(data[:3])
            loss = F.mse_loss(predicted[0][0].to(torch.float32), data[3].to(torch.float32).to(self.model.device))
            loss_total += loss.item()
            testCorrect.append(data[3].to(torch.float32))
            testPredict.append(predicted[0][0].to(torch.float32))

        testCorrect = torch.stack(testCorrect).detach().cpu().numpy()
        testPredict = torch.stack(testPredict).detach().cpu().numpy()
        rmse_test = np.sqrt(mean_squared_error(testCorrect, testPredict))
        r2_test = r2_score(testCorrect, testPredict)
        print('Test RMSE: %.4f , R2: %.4f' %(rmse_test, r2_test))
        # torch.cuda.empty_cache()
        return loss_total, rmse_test, r2_test