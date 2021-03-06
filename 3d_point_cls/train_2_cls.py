"""
Author: Benny
Date: Nov 2019
"""
from data_utils.ModelNetDataLoader import ModelNetDataLoader
import argparse
import numpy as np
import os
import torch
import datetime
import logging
from pathlib import Path
from tqdm import tqdm
import sys
import provider
import importlib
import shutil
from pprint import pprint
from data import getData
import time
from utils import  Logger,  savefig
from models.loss.sign_loss import SignLoss

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = BASE_DIR
sys.path.append(os.path.join(ROOT_DIR, 'models'))

parser = argparse.ArgumentParser('PointNet')
parser.add_argument('--seed', type=int, default=0, help=' seed value [default: 0]')
parser.add_argument('--batch_size', type=int, default=16, help='batch size in training [default: 24]')
parser.add_argument('--dataset', type=str, default="modelnet", help='Point Number [default: shapenet, modelnet]')
parser.add_argument('--model', default='pointnet_cls_our_bn', help='model name [default: pointnet_cls_our_bn,pointnet_cls_our_gn]')
parser.add_argument('--epoch',  default=300, type=int, help='number of epoch in training [default: 200]')
parser.add_argument('--learning_rate', default=0.001, type=float, help='learning rate in training [default: 0.001]')
parser.add_argument('--beta', default=1, type=float, help='weights of ori loss [default: 1]')
parser.add_argument('--gpu', type=str, default='0', help='specify gpu device [default: 0]')
parser.add_argument('--num_point', type=int, default=1024, help='Point Number [default: 1024]')
parser.add_argument('--num_class', type=int, default=40, help='Class Number [default: 40]')
parser.add_argument('--optimizer', type=str, default='Adam', help='optimizer for training [default: Adam]')
parser.add_argument('--log_dir', type=str, default=None, help='experiment root')
parser.add_argument('--remark', type=str, default=None, help='exp remark')
parser.add_argument('--task', type=str, default='ALL', help='exp task')
parser.add_argument('--norm', type=str, default='our5', help='type of normlization [default: P-BN-AK,BN, BNCE, GN, GNCE]')
parser.add_argument('--decay_rate', type=float, default=1e-4, help='decay rate [default: 1e-4]')
parser.add_argument('--normal', action='store_true', default=False, help='Whether to use normal information [default: False]')

def test(model, loader, num_class=40, ind=0):
    args = parser.parse_args()
    MODEL = importlib.import_module(args.model)
    criterion = MODEL.get_loss().cuda()
    mean_loss = []
    mean_correct = []
    class_acc = np.zeros((num_class,3))
    model.eval()
    for j, data in tqdm(enumerate(loader), total=len(loader)):
        points, target = data
        points = points.transpose(2, 1)
        points, target = points.cuda(), target.cuda()
        pred, trans_feat = model(points,ind=ind)
        loss = criterion(pred, target.long(), trans_feat)
        mean_loss.append(loss.item() / float(points.size()[0]))
        pred_choice = pred.data.max(1)[1]
        for cat in np.unique(target.cpu()):
            classacc = pred_choice[target==cat].eq(target[target==cat].long().data).cpu().sum()
            class_acc[cat,0]+= classacc.item()/float(points[target==cat].size()[0])
            class_acc[cat,1]+=1
        correct = pred_choice.eq(target.long().data).cpu().sum()
        mean_correct.append(correct.item()/float(points.size()[0]))
    class_acc[:,2] =  class_acc[:,0]/ class_acc[:,1]
    class_acc = np.mean(class_acc[:,2])
    instance_acc = np.mean(mean_correct)
    val_loss = np.mean(mean_loss)
    return val_loss, instance_acc, class_acc



def main():
    args = parser.parse_args()
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed(args.seed)
    np.random.seed(args.seed)

    if args.remark != None:
        args.remark = args.remark
    else:
        args.remark = args.dataset + "-" + args.task + "-" + args.norm

    if args.dataset =="shapenet":
        args.num_class=16
    else:
        args.num_class=40


    def log_string(str):
        logger.info(str)
        print(str)

    '''HYPER PARAMETER'''
    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu

    '''CREATE DIR'''
    timestr = str(datetime.datetime.now().strftime('%Y-%m-%d_%H-%M'))
    # experiment_dir = Path('./exp/v2/')
    experiment_dir = Path('/data-x/g12/zhangjie/3dIP/exp3.0/v2')
    # experiment_dir = Path('/data-x/g10/zhangjie/3D/exp/v2')
    experiment_dir.mkdir(exist_ok=True)
    experiment_dir = experiment_dir.joinpath('classification')
    experiment_dir.mkdir(exist_ok=True)
    experiment_dir = experiment_dir.joinpath(args.remark +"_"+ timestr)
    experiment_dir.mkdir(exist_ok=True)
    checkpoints_dir = experiment_dir.joinpath('checkpoints/')
    checkpoints_dir.mkdir(exist_ok=True)
    log_dir = experiment_dir.joinpath('logs/')
    log_dir.mkdir(exist_ok=True)

    '''LOG_curve'''
    title = args.dataset + "-" + args.task + "-" + args.norm
    logger_loss = Logger(os.path.join(log_dir, 'log_loss.txt'), title=title)
    logger_loss.set_names([ 'Train AVE Loss', 'Train Public Loss', 'Train Private Loss', 'Valid AVE Loss', 'Valid Public Loss', 'Valid Private Loss'])
    logger_acc = Logger(os.path.join(log_dir, 'log_acc.txt'), title=title)
    logger_acc.set_names([ 'Train Public Acc.', 'Train Private Acc.',  'Test Public Acc.', 'Test Private Acc.'])

    '''LOG'''  #创建log文件
    logger = logging.getLogger("Model") #log的名字
    # print("FFFFFFFF",logger) #<Logger Model (WARNING)>
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler('%s/%s.txt' % (log_dir, args.model))
    file_handler.setLevel(logging.INFO) #log的最低等级
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)  #log文件名
    log_string('PARAMETER ...')
    # print("FFFFFFF",logger.info)  #<bound method Logger.info of <Logger Model (INFO)>>
    log_string(args)

    '''DATA LOADING'''
    log_string('Load dataset ...')
    if args.dataset == "shapenet":
        trainDataLoader = getData.get_dataLoader(train=True, Shapenet=True, batchsize=args.batch_size)
        testDataLoader = getData.get_dataLoader(train=False,Shapenet=True, batchsize=args.batch_size)
    else:
        trainDataLoader = getData.get_dataLoader(train=True, Shapenet=False, batchsize=args.batch_size)
        testDataLoader = getData.get_dataLoader(train=False,Shapenet=False, batchsize=args.batch_size)

    log_string('Finished ...')
    log_string('Load model ...')

    '''MODEL LOADING'''
    num_class = args.num_class
    MODEL = importlib.import_module(args.model)
    # 当在写代码时，我们希望能够根据传入的选项设置，如args.model来确定要导入使用的是哪个model.py文件，而不是一股脑地导入， 这种时候就需要用上python的动态导入模块

    # 复制model文件到exp——dir
    shutil.copy('./models/%s.py' % args.model, str(experiment_dir))
    shutil.copy('./models/pointnet_util.py', str(experiment_dir))
    shutil.copy('train_2_cls.py', str(experiment_dir))
    shutil.copy('./data/getData.py', str(experiment_dir))
    shutil.copytree('./models/layers', str(experiment_dir)+"/layers")

    classifier = MODEL.get_model(num_class, channel=3).cuda()
    criterion = MODEL.get_loss().cuda()

    pprint(classifier)

    try:
        checkpoint = torch.load(str(experiment_dir) + '/checkpoints/best_model.pth')
        start_epoch = checkpoint['epoch']
        classifier.load_state_dict(checkpoint['model_state_dict'])
        log_string('Use pretrain model')
    except:
        log_string('No existing model, starting training from scratch...')
        start_epoch = 0


    if args.optimizer == 'Adam':
        optimizer = torch.optim.Adam(
            classifier.parameters(),
            lr=args.learning_rate,
            betas=(0.9, 0.999),
            eps=1e-08,
            weight_decay=args.decay_rate
        )
    else:
        optimizer = torch.optim.SGD(classifier.parameters(), lr=0.01, momentum=0.9)

    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.7)
    global_epoch = 0
    global_step = 0
    best_instance_acc = 0.0
    best_class_acc = 0.0
    mean_correct = []
    mean_correct2 = []
    mean_loss = []
    mean_loss1 = []
    mean_loss2 = []



    '''TRANING'''
    logger.info('Start training...')
    for epoch in range(start_epoch,args.epoch):
        time_start = datetime.datetime.now()
        log_string('Epoch %d (%d/%s):' % (global_epoch + 1, epoch + 1, args.epoch))

        scheduler.step()
        for batch_id, data in tqdm(enumerate(trainDataLoader, 0), total=len(trainDataLoader), smoothing=0.9):
            points, target = data
            points = points.data.numpy()
            points = provider.random_point_dropout(points)  #provider是自己写的一个对点云操作的函数，随机dropout，置为第一个点的值
            points[:,:, 0:3] = provider.random_scale_point_cloud(points[:,:, 0:3]) #点的放缩
            points[:,:, 0:3] = provider.shift_point_cloud(points[:,:, 0:3])   #点的偏移
            points = torch.Tensor(points)
            points = points.transpose(2, 1)
            points, target = points.cuda(), target.cuda()
            optimizer.zero_grad()
            classifier = classifier.train()

            for m in classifier.modules():
                if isinstance(m, SignLoss):
                    m.reset()

            loss1 = torch.tensor(0.).cuda()
            loss2 = torch.tensor(0.).cuda()
            sign_loss = torch.tensor(0.).cuda()

            for ind in range(2):
                if ind == 0:
                    pred, trans_feat = classifier(points,ind=ind)
                    loss1 = criterion(pred, target.long(), trans_feat)
                    mean_loss1.append(loss1.item() / float(points.size()[0]))
                    pred_choice = pred.data.max(1)[1]
                    correct = pred_choice.eq(target.long().data).cpu().sum()
                    mean_correct.append(correct.item() / float(points.size()[0]))

                else:
                    pred2, trans_feat2 = classifier(points,ind=ind)
                    loss2 = criterion(pred2, target.long(), trans_feat2)
                    mean_loss2.append(loss2.item() / float(points.size()[0]))
                    pred_choice2 = pred2.data.max(1)[1]
                    correct2 = pred_choice2.eq(target.long().data).cpu().sum()
                    mean_correct2.append(correct2.item() / float(points.size()[0]))

            for m in classifier.modules():
                if isinstance(m, SignLoss):
                    sign_loss += m.loss

            loss = args.beta * loss1 +loss2 + sign_loss
            mean_loss.append(loss.item() / float(points.size()[0]))

            # loss = loss2
            loss.backward()
            optimizer.step()
            global_step += 1

        train_instance_acc = np.mean(mean_correct)
        train_instance_acc2 = np.mean(mean_correct2)
        train_instance_acc_ave = (train_instance_acc + train_instance_acc2)/2
        train_loss = np.mean(mean_loss)/2
        train_loss1 = np.mean(mean_loss1)
        train_loss2 = np.mean(mean_loss2)

        log_string('Train Instance Public Accuracy: %f' % train_instance_acc)
        log_string('Train Instance Private Accuracy: %f' % train_instance_acc2)

        sign_acc = torch.tensor(0.).cuda()
        count = 0

        for m in classifier.modules():
            if isinstance(m, SignLoss):
                sign_acc += m.acc
                count += 1

        if count != 0:
            sign_acc /= count

        log_string('Sign Accuracy: %f' % sign_acc)

        with torch.no_grad():
            for ind in range(2):
                if ind == 0:
                    val_loss1, test_instance_acc1, class_acc1 = test(classifier, testDataLoader, num_class= args.num_class, ind=0)
                else:
                    val_loss2, test_instance_acc2, class_acc2 = test(classifier, testDataLoader, num_class= args.num_class, ind =1)

            log_string('Test Instance Public Accuracy: %f, Class Public Accuracy: %f'% (test_instance_acc1, class_acc1))
            log_string('Test Instance Private Accuracy: %f, Class Private Accuracy: %f'% (test_instance_acc2, class_acc2))

            val_loss = (val_loss1 + val_loss2)/2
            test_instance_acc = (test_instance_acc1 + test_instance_acc2)/2
            class_acc = (class_acc1 + class_acc2)/2

            if (test_instance_acc >= best_instance_acc):
                best_instance_acc = test_instance_acc
                best_epoch = epoch + 1

            if (class_acc >= best_class_acc):
                best_class_acc = class_acc
            log_string('Test Instance Average Accuracy: %f, Class Average Accuracy: %f'% (test_instance_acc, class_acc))
            log_string('Best Instance Average Accuracy: %f, Class Average Accuracy: %f'% (best_instance_acc, best_class_acc))

            if (test_instance_acc >= best_instance_acc):
                logger.info('Save model...')
                savepath = str(checkpoints_dir) + '/best_model.pth'
                log_string('Saving at %s'% savepath)
                log_string('best_epoch %s'% str(best_epoch))
                state = {
                    'epoch': best_epoch,
                    'instance_acc': test_instance_acc,
                    'class_acc': class_acc,
                    'model_state_dict': classifier.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                }
                torch.save(state, savepath)
            global_epoch += 1

        logger_loss.append([train_loss, train_loss1, train_loss2, val_loss, val_loss1, val_loss2])
        logger_acc.append([ train_instance_acc, train_instance_acc2,  test_instance_acc1, test_instance_acc2])

        time_end = datetime.datetime.now()
        time_span_str = str((time_end - time_start).seconds)
        log_string('Epoch time : %s S' % (time_span_str))

    logger_loss.close()
    logger_loss.plot()
    savefig(os.path.join(log_dir, 'log_loss.eps'))
    logger_acc.close()
    logger_acc.plot()
    savefig(os.path.join(log_dir, 'log_acc.eps'))

    log_string('best_epoch %s' % str(best_epoch))

    logger.info('End of training...')



if __name__ == '__main__':
    main()
