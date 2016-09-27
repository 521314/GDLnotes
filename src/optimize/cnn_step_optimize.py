from __future__ import print_function

import random

import tensorflow as tf

from convnet.conv_mnist import maxpool2d
from neural.full_connect import accuracy
from util.mnist import format_mnist
from util.request import better_trend_hyper


def large_data_size(data):
    return data.get_shape()[1] > 1 and data.get_shape()[2] > 1


def conv_train(train_dataset, train_labels, valid_dataset, valid_labels, test_dataset, test_labels, image_size,
               num_labels, basic_hps, stride_ps):
    batch_size = basic_hps['batch_size']
    patch_size = basic_hps['patch_size']
    depth = basic_hps['depth']
    if depth < 2:
        depth = 2
    num_hidden = basic_hps['num_hidden']
    if num_hidden < 4:
        num_hidden = 4
    num_channels = 1
    layer_cnt = basic_hps['layer_sum']
    starter_learning_rate = basic_hps['starter_learning_rate']
    loss_collect = list()
    first_hidden_num = num_hidden
    second_hidden_num = first_hidden_num / 2 + 1

    graph = tf.Graph()
    with graph.as_default():
        # Input data.
        tf_train_dataset = tf.placeholder(
            tf.float32, shape=(batch_size, image_size, image_size, num_channels))
        tf_train_labels = tf.placeholder(tf.float32, shape=(batch_size, num_labels))
        tf_valid_dataset = tf.constant(valid_dataset)
        tf_test_dataset = tf.constant(test_dataset)

        input_weights = tf.Variable(tf.truncated_normal(
            [patch_size, patch_size, num_channels, depth], mean=-0.1, stddev=0.1))
        input_biases = tf.Variable(tf.zeros([depth]))
        mid_layer_cnt = layer_cnt - 1
        layer_weights = list()
        layer_biases = [tf.Variable(tf.constant(1.0, shape=[depth / (i + 2)])) for i in range(mid_layer_cnt)]
        output_weights = list()
        output_biases = tf.Variable(tf.constant(1.0, shape=[num_hidden]))
        first_nn_weights = tf.Variable(tf.truncated_normal(
            [first_hidden_num, second_hidden_num], mean=-0.1,stddev=0.1))
        second_nn_weights = tf.Variable(tf.truncated_normal(
            [second_hidden_num, num_labels], mean=-0.1,stddev=0.1))
        first_nn_biases = tf.Variable(tf.constant(1.0, shape=[second_hidden_num]))
        second_nn_biases = tf.Variable(tf.constant(1.0, shape=[num_labels]))

        # Model.
        def model(data, init=False):
            # Variables.
            if not large_data_size(data) or not large_data_size(input_weights):
                stride_ps[0] = [1, 1, 1, 1]
            conv = tf.nn.conv2d(data, input_weights, stride_ps[0], use_cudnn_on_gpu=True, padding='SAME')
            print(conv)
            conv = maxpool2d(conv)
            print(conv)
            hidden = tf.nn.relu(conv + input_biases)
            if init:
                hidden = tf.nn.dropout(hidden, 0.8)
            for i in range(mid_layer_cnt):
                # print(hidden)
                if init:
                    hid_shape = hidden.get_shape()
                    filter_w = patch_size / (i + 1)
                    filter_h = patch_size / (i + 1)
                    if filter_w > hid_shape[1]:
                        filter_w = int(hid_shape[1])
                    if filter_h > hid_shape[2]:
                        filter_h = int(hid_shape[2])
                    layer_weight = tf.Variable(tf.truncated_normal(shape=[filter_w, filter_h, depth / (i + 1), depth / (i + 2)],
                                                                   mean=-0.1, stddev=0.1))
                    layer_weights.append(layer_weight)
                if not large_data_size(hidden) or not large_data_size(layer_weights[i]):
                    stride_ps[i + 1] = [1, 1, 1, 1]
                conv = tf.nn.conv2d(hidden, layer_weights[i], stride_ps[i + 1], use_cudnn_on_gpu=True, padding='SAME')
                print(conv)
                if not large_data_size(conv):
                    conv = maxpool2d(conv, 1, 1)
                else:
                    conv = maxpool2d(conv)
                print(conv)
                hidden = tf.nn.relu(conv + layer_biases[i])
                if init:
                    hidden = tf.nn.dropout(hidden, 0.8)

            shapes = hidden.get_shape().as_list()
            shape_mul = 1
            for s in shapes[1:]:
                shape_mul *= s

            if init:
                output_size = shape_mul
                output_weights.append(tf.Variable(tf.truncated_normal([output_size, num_hidden], mean=-0.1, stddev=0.1)))
            reshape = tf.reshape(hidden, [shapes[0], shape_mul])

            hidden = tf.nn.relu6(tf.matmul(reshape, output_weights[0]) + output_biases)
            if init:
                hidden = tf.nn.dropout(hidden, 0.5)
            hidden = tf.matmul(hidden, first_nn_weights) + first_nn_biases
            if init:
                hidden = tf.nn.dropout(hidden, 0.5)
            hidden = tf.matmul(hidden, second_nn_weights) + second_nn_biases
            return hidden

        # Training computation.
        logits = model(tf_train_dataset, init=True)
        loss = tf.reduce_mean(
            tf.nn.softmax_cross_entropy_with_logits(logits, tf_train_labels))
        optimizer = tf.train.AdagradOptimizer(starter_learning_rate).minimize(loss)

        train_prediction = tf.nn.softmax(logits)
        valid_prediction = tf.nn.softmax(model(tf_valid_dataset))
        test_prediction = tf.nn.softmax(model(tf_test_dataset))
    num_steps = 1001

    with tf.Session(graph=graph) as session:
        tf.initialize_all_variables().run()
        print('Initialized')
        mean_loss = 0
        for step in range(num_steps):
            offset = (step * batch_size) % (train_labels.shape[0] - batch_size)
            batch_data = train_dataset[offset:(offset + batch_size), :, :, :]
            batch_labels = train_labels[offset:(offset + batch_size), :]
            feed_dict = {tf_train_dataset: batch_data, tf_train_labels: batch_labels}
            _, l, predictions = session.run(
                [optimizer, loss, train_prediction], feed_dict=feed_dict)
            mean_loss += l
            if step % 10 == 0:
                mean_loss /= 10.0
                if step % 50 == 0:
                    loss_collect.append(mean_loss)
                mean_loss = 0
                if step % 50 == 0:
                    print('Minibatch loss at step %d: %f' % (step, l))
                    print('Validation accuracy: %.1f%%' % accuracy(
                        valid_prediction.eval(), valid_labels))
        print('Test accuracy: %.1f%%' % accuracy(test_prediction.eval(), test_labels))
        hypers = better_trend_hyper([batch_size, depth, num_hidden, layer_cnt, patch_size], loss_collect)
        print(hypers)
        for i in range(len(hypers)):
            if hypers[i] <= 1.0:
                hypers[i] = 1
            else:
                hypers[i] = int(hypers[i])
        hypers.append(starter_learning_rate)
    return hypers


def valid_hp(hps):
    one_hp_cnt = 0
    for hp in hps:
        if hp <= 1:
            one_hp_cnt += 1
    if one_hp_cnt == len(hps):
        print('all hp is one, change:')
        for i in range(len(hps)):
            hps[i] *= random.randint(0, 10)
        print(hps)
    return True


def fit_better():
    image_size = 28
    num_labels = 10
    train_dataset, train_labels, valid_dataset, valid_labels, test_dataset, test_labels = \
        format_mnist()
    pick_size = 2048
    valid_dataset = valid_dataset[0: pick_size, :, :, :]
    valid_labels = valid_labels[0: pick_size, :]
    test_dataset = test_dataset[0: pick_size, :, :, :]
    test_labels = test_labels[0: pick_size, :]
    basic_hypers = {
        'batch_size': 10,
        'patch_size': 10,
        'depth': 10,
        'num_hidden': 10,
        'layer_sum': 3,
        'starter_learning_rate': 0.1
    }
    if basic_hypers['patch_size'] > 28:
        basic_hypers['patch_size'] = 28

    print('=' * 80)
    print(basic_hypers)

    stride_params = [[1, 2, 2, 1] for _ in range(basic_hypers['layer_sum'])]
    better_hps = conv_train(train_dataset, train_labels, valid_dataset, valid_labels, test_dataset, test_labels,
                                 image_size, num_labels, basic_hypers, stride_params)
    while valid_hp(better_hps):
        basic_hypers = {
            'batch_size': better_hps[0],
            'patch_size': better_hps[4],
            'depth': better_hps[1],
            'num_hidden': better_hps[2],
            'layer_sum': better_hps[3],
            'starter_learning_rate': better_hps[5]
        }
        # if basic_hypers['batch_size'] < 10:
        #     basic_hypers['batch_size'] = 10
        if basic_hypers['patch_size'] > 28:
            basic_hypers['patch_size'] = 28
        print('=' * 80)
        print(basic_hypers)
        stride_params = [[1, 2, 2, 1] for _ in range(basic_hypers['layer_sum'])]
        better_hps = conv_train(
            train_dataset, train_labels, valid_dataset, valid_labels, test_dataset, test_labels,
            image_size, num_labels, basic_hypers, stride_params)
    else:
        print('can not find better hypers')


if __name__ == '__main__':
    fit_better()
