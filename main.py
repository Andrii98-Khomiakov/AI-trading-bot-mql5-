"""
Main function for training and evaluating agents in traffic envs
@author: Tianshu Chu
run command: 
1. Train: python main.py --base-dir real_net/ma2c train --config-dir config/config_ma2c_real.ini --test-mode no_test
2. Visualize: python main.py --base-dir real_net evaluate --agents ma2c 
"""

import argparse
import configparser
import logging
import tensorflow.compat.v1 as tf
import threading
from envs.real_net_env import RealNetEnv, RealNetController
from agents.models import MA2C
from utils import (Counter, Trainer, Tester, Evaluator,
                   check_dir, copy_file, find_file,
                   init_dir, init_log, init_test_flag)


def parse_args():
    default_base_dir = '/Users/tchu/Documents/rl_test/signal_control_results/eval_sep2019/large_grid'
    default_config_dir = './config/config_test_large.ini'
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-dir', type=str, required=False,
                        default=default_base_dir, help="experiment base dir")
    subparsers = parser.add_subparsers(dest='option', help="train or evaluate")
    sp = subparsers.add_parser(
        'train', help='train a single agent under base dir')
    sp.add_argument('--test-mode', type=str, required=False,
                    default='no_test',
                    help="test mode during training",
                    choices=['no_test', 'in_train_test', 'after_train_test', 'all_test'])
    sp.add_argument('--config-dir', type=str, required=False,
                    default=default_config_dir, help="experiment config path")
    sp = subparsers.add_parser(
        'evaluate', help="evaluate and compare agents under base dir")
    sp.add_argument('--agents', type=str, required=False,
                    default='naive', help="agent folder names for evaluation, split by ,")
    sp.add_argument('--evaluation-policy-type', type=str, required=False, default='default',
                    help="inference policy type in evaluation: default, stochastic, or deterministic")
    args = parser.parse_args()
    if not args.option:
        parser.print_help()
        exit(1)
    return args


def init_env(config, port=1, naive_policy=False):
    if not naive_policy:
        return RealNetEnv(config, port=port)
    else:
        env = RealNetEnv(config, port=port)
        policy = RealNetController(env.node_names, env.nodes)
        return env, policy


def train(args):
    base_dir = args.base_dir
    dirs = init_dir(base_dir)
    init_log(dirs['log'])
    config_dir = args.config_dir
    copy_file(config_dir, dirs['data'])
    config = configparser.ConfigParser()
    config.read(config_dir)
    in_test, post_test = init_test_flag(args.test_mode)

    # init env
    env = init_env(config['ENV_CONFIG'])
    logging.info('Training: s dim: %d, a dim %d, s dim ls: %r, a dim ls: %r' %
                 (env.n_s, env.n_a, env.n_s_ls, env.n_a_ls))

    # init step counter
    total_step = int(config.getfloat('TRAIN_CONFIG', 'total_step'))
    test_step = int(config.getfloat('TRAIN_CONFIG', 'test_interval'))
    log_step = int(config.getfloat('TRAIN_CONFIG', 'log_interval'))
    global_counter = Counter(total_step, test_step, log_step)

    # init centralized or multi agent
    seed = config.getint('ENV_CONFIG', 'seed')
    model = MA2C(env.n_s_ls, env.n_a_ls, env.n_w_ls, env.n_f_ls, total_step,
                 config['MODEL_CONFIG'], seed=seed)

    # disable multi-threading for safe SUMO implementation
    summary_writer = tf.summary.FileWriter(dirs['log'])
    trainer = Trainer(env, model, global_counter,
                      summary_writer, in_test, output_path=dirs['data'])
    trainer.run()
    # post-training test
    if post_test:
        tester = Tester(env, model, global_counter,
                        summary_writer, dirs['data'])
        tester.run_offline(dirs['data'])

    # save model
    final_step = global_counter.cur_step
    logging.info('Training: save final model at step %d ...' % final_step)
    model.save(dirs['model'], final_step)


def evaluate_fn(agent_dir, output_dir, port, policy_type):
    agent = agent_dir.split('/')[-1]
    if not check_dir(agent_dir):
        logging.error('Evaluation: %s does not exist!' % agent)
        return
    # load config file for env
    config_dir = find_file(agent_dir + '/data/')
    if not config_dir:
        return
    config = configparser.ConfigParser()
    config.read(config_dir)

    # init env
    env = init_env(config['ENV_CONFIG'], port)
    logging.info('Evaluation: s dim: %d, a dim %d, s dim ls: %r, a dim ls: %r' %
                 (env.n_s, env.n_a, env.n_s_ls, env.n_a_ls))

    # load model for agent
    # init centralized or multi agent
    model = MA2C(env.n_s_ls, env.n_a_ls, env.n_w_ls,
                 env.n_f_ls, 0, config['MODEL_CONFIG'])
    if not model.load(agent_dir + '/model/'):
        return
    print('agent', agent)
    print('env.agent', env.agent)
    env.agent = agent
    # collect evaluation data
    evaluator = Evaluator(env, model, output_dir, policy_type=policy_type)
    evaluator.run()


def evaluate(args):
    base_dir = args.base_dir
    dirs = init_dir(base_dir, pathes=['eva_data', 'eva_log'])
    init_log(dirs['eva_log'])
    agents = args.agents.split(',')
    print('agents', agents)
    # enforce the same evaluation seeds across agents
    policy_type = args.evaluation_policy_type
    logging.info('Evaluation: policy type: %s' %
                 (policy_type))

    threads = []
    for i, agent in enumerate(agents):
        print('agent', agent)
        agent_dir = base_dir + '/' + agent
        thread = threading.Thread(target=evaluate_fn,
                                  args=(agent_dir, dirs['eva_data'], i, policy_type))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()


if __name__ == '__main__':
    args = parse_args()
    if args.option == 'train':
        train(args)
    else:
        evaluate(args)