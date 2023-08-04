import model
import torch
import random
import timeit
import json

if __name__ == "__main__":

    model_name = 'Kcat'

    args = {
        "dim" : 20,
        "layer_output" : 3,
        "layer_gnn" : 3,
        "layer_dnn" : 3,
        "lr" : 1e-4,
        "weight_decay": 1e-6,
        "epoch" : 100
    }

    file_model = './model/output/' + model_name
    file_MAEs  = './model/output/' + model_name + '-MAEs.csv'
    file_args  = './model/output/' + model_name + '-args.json'

    dir_input = './data/'
    compound_fingerprints = model.load_pickle(dir_input + 'compound_fingerprints.pickle')
    adjacencies = model.load_pickle(dir_input + 'adjacencies.pickle')
    proteins_local = model.load_pickle(dir_input + 'local_representations.pickle')
    # proteins_global = model.load_pickle(dir_input + 'global_representations.pickle')
    fingerprint_dict = model.load_pickle(dir_input + 'fingerprint_dict.pickle')
    args['len_fingerprint'] = len(fingerprint_dict)
    Kcat = model.load_pickle(dir_input + 'Kcats.pickle')
    Kcat = torch.FloatTensor(Kcat)

    if not (len(compound_fingerprints) == len(adjacencies) == len(proteins_local) == len(Kcat)):
        print('The length of compound_fingerprints, adjacencies and proteins are not equal !!!')
        exit()

    dataset = list(zip(compound_fingerprints, adjacencies, proteins_local, Kcat))
    random.seed(233)
    random.shuffle(dataset)
    dataset_train, dataset_ = model.split_dataset(dataset, 0.8)
    dataset_dev, dataset_test = model.split_dataset(dataset_, 0.5)

    """CPU or GPU."""
    if torch.cuda.is_available():
        device = torch.device('cuda')
        print('The code uses GPU !!!')
    else:
        device = torch.device('cpu')
        print('The code uses CPU !!!')

    torch.manual_seed(random.randint(1, 10000))
    Kcatpredictor = model.KcatPrediction(args, device).to(device)
    trainer = model.Trainer(Kcatpredictor)
    tester = model.Tester(Kcatpredictor)

    """Output files."""
    with open(file_args, 'w') as f:
        f.write(str(json.dumps(args)) + '\n')

    """Start training."""
    print('Training...')
    MAEs = []
    start = timeit.default_timer()
    for epoch in range(0, args["epoch"]):
        print('Epoch: %d / %d' % (epoch + 1, args["epoch"]))
        LOSS_train, RMSE_train, R2_train, Lr = trainer.train(dataset_train)
        LOSS_dev, RMSE_dev, R2_dev = tester.test(dataset_dev)
        end = timeit.default_timer()
        time = end - start
        MAE = [epoch+1, time, LOSS_train, RMSE_train, R2_train, 
                            LOSS_dev,  RMSE_dev,  R2_dev,  Lr]
        MAEs.append(MAE)

        if (epoch) % 20 == 0:
            torch.save(Kcatpredictor.state_dict(), file_model +'_'+ str(epoch) + ".pth")
        """save MAEs as csv file every 10 epoch"""
        with open(file_MAEs, 'w') as f:
            f.write('epoch,time,LOSS_train,RMSE_train,R2_train,LOSS_dev,RMSE_dev,R2_dev,Lr\n')
            for MAE in MAEs:
                f.write(str(MAE)[1:-1] + '\n')
        # print('MAEs saved to %s' % file_MAEs)

    print("on the test set:")
    LOSS_test, RMSE_test, R2_test = tester.test(dataset_test)

    """Save the trained model."""
    torch.save(Kcatpredictor.state_dict(), file_model + ".pth")
    print('Model saved to %s' % file_model)

    """save MAEs as csv file"""
    with open(file_MAEs, 'w') as f:
        f.write('epoch,time,LOSS_train,RMSE_train,R2_train,LOSS_dev,RMSE_dev,R2_dev,Lr\n')
        for MAE in MAEs:
            f.write(str(MAE)[1:-1] + '\n')
    print('MAEs saved to %s' % file_MAEs)

        



