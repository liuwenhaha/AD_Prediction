import argparse
import logging

import torch
import torch.nn as nn
from torch import cuda
from torch.autograd import Variable
from torch.utils.data import DataLoader,Dataset

import torchvision
import torchvision.datasets as dset
import torchvision.transforms as transforms
import torchvision.utils
from PIL import Image

import torch.nn.functional as F

import matplotlib.pyplot as plt
import numpy as np
import random

from sklearn.preprocessing import OneHotEncoder

from custom_transform import CustomResize

from AD_Dataset import AD_Dataset
from ResNet import ResNet
from AlexNet import AlexNet


logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)

parser = argparse.ArgumentParser(description="Starter code for JHU CS661 Computer Vision HW3.")

parser.add_argument("--network_type", "--nt", default="AlexNet", choices=["AlexNet", "ResNet"],
                    help="Deep network type. (default=AlexNet)")
parser.add_argument("--load",
                    help="Load saved network weights.")
parser.add_argument("--save", default="best_model",
                    help="Save network weights.")  
parser.add_argument("--augmentation", default=True, type=bool,
                    help="Save network weights.")
parser.add_argument("--epochs", default=20, type=int,
                    help="Epochs through the data. (default=20)")  
parser.add_argument("--learning_rate", "-lr", default=1e-3, type=float,
                    help="Learning rate of the optimization. (default=0.01)")
parser.add_argument("--estop", default=1e-2, type=float,
                    help="Early stopping criteria on the development set. (default=1e-2)")               
parser.add_argument("--batch_size", default=1, type=int,
                    help="Batch size for training. (default=1)")
parser.add_argument("--optimizer", default="Adam", choices=["SGD", "Adadelta", "Adam"],
                    help="Optimizer of choice for training. (default=Adam)")
parser.add_argument("--gpuid", default=[0], nargs='+', type=int,
                    help="ID of gpu device to use. Empty implies cpu usage.")
# feel free to add more arguments as you need


def main(options):
    # Path configuration
    TRAINING_PATH = 'train.txt'
    TESTING_PATH = 'test.txt'
    IMG_PATH = './Image'

    trg_size = (110, 110, 110)
    transformations = transforms.Compose([CustomResize(trg_size),
                                    transforms.ToTensor()
                                    ])


    dset_train = AD_Dataset(IMG_PATH, TRAINING_PATH, transformations)
    dset_test = AD_Dataset(IMG_PATH, TESTING_PATH, transformations)

    # Use argument load to distinguish training and testing
    if options.load is None:
        train_loader = DataLoader(dset_train,
                                  batch_size = options.batch_size,
                                  shuffle = True,
                                  num_workers = 4
                                 )
    else:
        # Only shuffle the data when doing training
        train_loader = DataLoader(dset_train,
                                  batch_size=options.batch_size,
                                  shuffle=False,
                                  num_workers=4
                                  )

    test_loader = DataLoader(dset_test,
                             batch_size = options.batch_size,
                             shuffle = False,
                             num_workers = 4
                             )

    use_cuda = (len(options.gpuid) >= 1)
    if options.gpuid:
        cuda.set_device(options.gpuid[0])

    # Training process
    if options.load is None:
        # Initial the model
        if options.network_type == 'AlexNet':
            model = AlexNet()
        else:
            model = ResNet()

        if use_cuda > 0:
            model.cuda()
        else:
            model.cpu()

        # Binary cross-entropy loss
        criterion = torch.nn.NLLLoss()

        optimizer = eval("torch.optim." + options.optimizer)(model.parameters(), options.learning_rate)

        onehot_encoder = OneHotEncoder(sparse=False)

        # Prepare for label encoding
        last_dev_avg_loss = float("inf")
        best_accuracy = float("-inf")

        # main training loop
        for epoch_i in range(options.epochs):
            logging.info("At {0}-th epoch.".format(epoch_i))
            train_loss = 0.0
            correct_cnt = 0.0
            for it, train_data in enumerate(train_loader):
                data_dic = train_data

                if use_cuda:
                    imgs, labels = Variable(data_dic['image']).cuda(), Variable(data_dic['label']).cuda() 
                else:
                    imgs, labels = Variable(data_dic['image']), Variable(data_dic['label'])

                # add channel dimension: (batch_size, D, H ,W) to (batch_size, 1, D, H ,W)
                # since 3D convolution requires 5D tensors
                input_imgs = imgs.view(options.batch_size, 1, trg_size[0], trg_size[1], trg_size[2])
                integer_encoded = labels.data.cpu().numpy()
                # target should be LongTensor in loss function
                ground_truth = Variable(torch.from_numpy(integer_encoded)).long()
                if use_cuda:
                    ground_truth = ground_truth.cuda()
                train_output = model(input_imgs)
                train_prob_loss = F.log_softmax(train_output, dim=1)
                train_prob_predict = F.softmax(train_output, dim=1)
                _, predict = train_prob_predict.topk(1)
                loss = criterion(train_prob_loss, ground_truth)
                train_loss += loss
                correct_cnt += (predict.squeeze(1) == ground_truth).sum()
                accuracy = float(correct_cnt) / len(ground_truth)
                logging.debug("loss at batch {0}: {1}".format(it, loss.data[0]))
                logging.debug("accuracy at batch {0}: {1}".format(it, accuracy))
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            train_avg_loss = train_loss / (len(dset_train) / options.batch_size)
            train_avg_acu = float(correct_cnt) / len(dset_train)
            logging.info("Average training loss is {0} at the end of epoch {1}".format(train_avg_loss.data[0], epoch_i))
            logging.info("Average training accuracy is {0} at the end of epoch {1}".format(train_avg_acu, epoch_i))
            
            # validation -- this is a crude esitmation because there might be some paddings at the end
            dev_loss = 0.0
            correct_prediction = 0.0
            for it, test_data in enumerate(test_loader):
                data_dic = test_data

                if use_cuda:
                    imgs, labels = Variable(data_dic['image']).cuda(), Variable(data_dic['label']).cuda() 
                else:
                    imgs, labels = Variable(data_dic['image']), Variable(data_dic['label'])

                input_imgs = imgs.view(options.batch_size, 1, trg_size[0], trg_size[1], trg_size[2])
                integer_encoded = labels.data.cpu().numpy()
                ground_truth = Variable(torch.from_numpy(integer_encoded)).long()
                if use_cuda:
                    ground_truth = ground_truth.cuda()
                test_output = model(input_imgs)
                test_prob_loss = F.log_softmax(test_output, dim=1)
                test_prob_predict = F.softmax(test_output, dim=1)
                _, predict = test_prob_predict.topk(1)
                loss = criterion(test_prob_loss, ground_truth)
                dev_loss += loss
                correct_cnt += (predict.squeeze(1) == ground_truth).sum()

            dev_avg_loss = dev_loss / (len(dset_test) / options.batch_size)
            dev_avg_acu = float(correct_cnt) / len(dset_test)
            logging.info("Average validation loss is {0} at the end of epoch {1}".format(dev_avg_loss.data[0], epoch_i))
            logging.info("Average validation accuracy is {0} at the end of epoch {1}".format(dev_avg_acu, epoch_i))

            torch.save(model.state_dict(), open(options.save + ".nll_{0:.2f}.epoch_{1}".format(dev_avg_loss.data[0], epoch_i), 'wb'))

            last_dev_avg_loss = dev_avg_loss


if __name__ == "__main__":
  ret = parser.parse_known_args()
  options = ret[0]
  if ret[1]:
    logging.warning("unknown arguments: {0}".format(parser.parse_known_args()[1]))
  main(options)
