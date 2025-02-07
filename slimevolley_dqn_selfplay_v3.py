# -*- coding: utf-8 -*-
"""slimevolley_DQN_selfplay_v3.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/177VfyKgUTiDYoKUfn6Nw2lNDtbEEDFSR

# Colab specific chunk
Google drive file IO
If the script is run in colab, mounting will be required for file IO with google drive. Run this cell to authorize.
"""

IN_COLAB = 'google.colab' in sys.modules

IN_COLAB

if IN_COLAB:
    from google.colab import drive
    drive.mount('/content/drive')

"""# Dependencies"""

# Set seed for experiment reproducibility
# Does not work with GPU runtime
import numpy as np
import tensorflow as tf
import random

seed = 721

# For starting Numpy generated random numbers
# in a well-defined initial state.
np.random.seed(seed)

# For starting core Python generated random numbers
# in a well-defined state.
random.seed(seed)

# The below set_seed() will make random number generation
# in the TensorFlow backend have a well-defined initial state.
tf.random.set_seed(seed)

# Environment
import gym
import slimevolleygym

# Necessary for NN model
from tensorflow.keras import Sequential
from collections import deque
from tensorflow.keras.layers import Dense
from tensorflow.keras.optimizers import Adam

# For display progress
import time
import sys

# For saving and loading model
import os

"""# Self play training env"""

class SlimeVolleySelfPlayEnv(slimevolleygym.SlimeVolleyEnv):
    """
    Ref: https://github.com/hardmaru/slimevolleygym/blob/master/training_scripts/train_ppo_selfplay.py
    wrapper over the normal single player env, but loads the best self play model
    before finding the first best model, policy is random
    """
    def __init__(self):
        super(SlimeVolleySelfPlayEnv, self).__init__()
        self.policy = self
        self.best_model = None
        self.best_model_filepath = None
    
    def predict(self, state): # The environment policy based on the best model
        if self.best_model is None:
            return random.sample(range(8), 1)[0] # Return a random action code in action space
        else:
            act_values, _ = self.best_model.predict(state) # Use the best model to return action
            return np.argmax(act_values[0])

"""# Agent class - DQN"""

class DQN:
    """
    DQN agent class, responsible for building network
    """
    def __init__(self, 
                 agent_name,
                 state_space,
                 action_space,
                 epsilon_decay,
                 discount_rate,
                 learning_rate,
                 min_step_to_learn,
                 replay_memory,
                 batch_size,
                 target_update_interval,
                 training_interval):

        self.agent_name = agent_name

        self.state_space = state_space
        self.action_space = action_space

        # Default parameters
        self.epsilon = 1
        self.epsilon_min = .01

        # Hyperparameters
        self.epsilon_decay = epsilon_decay
        self.gamma = discount_rate
        self.update_target_model_freq = target_update_interval
        self.learning_rate = learning_rate
        self.min_step_to_learn = min_step_to_learn
        # For experience replay
        self.memory = deque(maxlen=replay_memory) # deque for memory management
        self.batch_size = batch_size
        self.training_interval = training_interval

        # Create models
        self.model = self.build_model() # Create training model
        self.target_model = self.build_model() # Create target model
        self.target_model.set_weights(self.model.get_weights()) # Initialize target mode
        
        # Statistics
        self.step = 0
        self.episode_scores = []
        self.episode_lengths = []
        self.scores = []
        self.scores_ma100 = [] # Not used
        self.scores_ma100_up = [] # Not used
        self.scores_ma100_lo = [] # Not used
        self.episodes_agg = 0
        self.timesteps_agg = 0
        self.time_start = time.process_time()


    def build_model(self):
        # Architecture
        model = Sequential()

        model.add(Dense(32, input_shape=(self.state_space,), activation='relu', 
                 kernel_initializer=tf.keras.initializers.VarianceScaling(
                 scale=2.0, mode='fan_in', distribution='truncated_normal'), 
                 name='dense1')) # Set input shape to initialize weights
        model.add(Dense(32, activation='relu',
                 kernel_initializer=tf.keras.initializers.VarianceScaling(
                 scale=2.0, mode='fan_in', distribution='truncated_normal'),
                 name='dense2'))
        model.add(Dense(8, activation='softmax', name='dense3'))
        
        model.compile(loss='mse', optimizer=Adam(lr=self.learning_rate))
        
        return model

    def act(self, state):
        if np.random.rand() > self.epsilon: # Epsilon greedy policy
            return self.act_greedy(state) # Exploit, action return 0...7
        else:
            return self.act_random() # Explore by choosing random action, 0...7

    def act_greedy(self, state): # For rollout, no random noise
        act_values = self.model.predict(state) # Predict
        return np.argmax(act_values[0]) # action return code 0...7

    def act_random(self):
        return random.sample(range(8), 1)[0] #2**env.action_space.shape[0])
    
    def update_replay_memory(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))

    def replay(self):
        # Start training only if sufficient number of samples is already saved
        if len(self.memory) < self.min_step_to_learn:
            return

        # Sample minibatch from the experience
        minibatch = random.sample(self.memory, self.batch_size)

        # Get s a r s' from minibatch
        states = np.array([i[0] for i in minibatch])
        actions = np.array([i[1] for i in minibatch])
        rewards = np.array([i[2] for i in minibatch])
        next_states = np.array([i[3] for i in minibatch])
        dones = np.array([i[4] for i in minibatch])

        states = np.squeeze(states) # Remove axis of length one
        next_states = np.squeeze(next_states)

        # Use target network for max_future_q
        # Maxima along the second axis
        max_future_q = (np.amax(self.target_model.predict_on_batch(next_states), axis=1)) * (1 - dones)
        
        targets = rewards + self.gamma * max_future_q # if done=1, max_future_q=0 => targets = reward
        targets_full = self.model.predict_on_batch(states)
        
        ind = np.array([i for i in range(self.batch_size)])
        targets_full[[ind], [actions]] = targets

        # Fit on all samples as one batch
        # Update weights
        self.model.fit(states, targets_full, batch_size=self.batch_size, epochs=1, verbose=0)
        # If use tensor board use, incomplete
        #self.model.fit(X, y, batch_size=self.batch_size, verbose=0, shuffle=False, callbacks=[self.tensorboard] if terminal_state else None)
        
        # Decay epsilon, less exploration, more exploitation
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
            self.epsilon = max(self.epsilon_min, self.epsilon)

    def update_target_model(self):
        self.target_model.set_weights(self.model.get_weights())

#    def plot_learning_curve2(self): # For slimevolley
#        # Plot total score vs episode
#        ep = len(self.scores)
#        fig, ax = plt.subplots()
#        ax.plot(self.scores,
#                color='blue', alpha=0.4, linewidth=0.5, 
#                label='Total score in each episode')
#        ax.hlines(0, xmin=0, xmax=ep, colors='red')
#        ax.set(xlabel='Episode', ylabel='Total score', ylim=[-5, 5], title='DQN with experience replay')
#        plt.legend(bbox_to_anchor=(1.04, 0), loc="lower left", borderaxespad=0)
#        plt.show()
#        return
    
    #def learn(self, total_timesteps, abort_training, tensorboard_log_name, log_interval):
        # training is limited by timesteps instead of episodes
        #return trained_model

    #def save(self):

"""# Functions

## function to map encoded actio to env action
"""

def action_inverse(num):
    """
    Map multibinary action space to 8 exclusive discrete action combinations
    """
    if num == 0:
        return np.array([0,0,0])
    elif num == 1:
        return np.array([1,0,0])
    elif num == 2:
        return np.array([0,1,0])
    elif num == 3:
        return np.array([0,0,1])
    elif num == 4:
        return np.array([1,1,0])
    elif num == 5:
        return np.array([1,0,1])
    elif num == 6:
        return np.array([0,1,1])
    elif num == 7:
        return np.array([1,1,1])

"""## Train 1 episode"""

def train_one_episode(env, agent, selfplay_mode=False):
    """
    Run one episode of training, i.e. until done=True, to collect experience and learn from replay.
    """
    
    #trainer = 'random' # Uncomment this to train against weak opponent
    trainer = 'expert' # Train against baseline policy in slimevolleygym
    
    state = env.reset()
    state = np.reshape(state, (1, 12))

    score = 0
    done = False
    step_before = agent.step

    while not done: # Within an episode

        agent.step += 1

        action = agent.act(state) # epsilon
        
        if selfplay_mode:
            # Train aginst on best model in the past
            next_state, reward, done, _ = env.step(action_inverse(action), action_inverse(env.predict(state)))
        else:
            if trainer == "random": # Train using random, rookie
                next_state, reward, done, _ = env.step(action_inverse(action), action_inverse(agent.act_random()))
            else: # Train using baseline, i.e. expert
                next_state, reward, done, _ = env.step(action_inverse(action))
    
        score += reward

        next_state = np.reshape(next_state, (1, 12))

        # Update replay memory
        agent.update_replay_memory(state, action, reward, next_state, done)

        # Train network every k step
        if agent.step % agent.training_interval == 0:
            agent.replay()

        # Update current state
        state = next_state

        # Update target model after certain timesteps
        if agent.step % agent.update_target_model_freq == 0:
            print(f'Target network update at step {agent.step}, epsilon {agent.epsilon}')
            agent.update_target_model()
            
    episode_return = score
    episode_length = agent.step - step_before
    
    return episode_return, episode_length

"""## Train N episodes"""

def train(env,
          agent,
          max_steps,
          eval_freq,
          eval_episodes,
          best_threshold=0,
          selfplay_mode=False,
          render_mode=False):

    """
    Function to train for N steps, wrapper of train_one_episode
    Input: agent, steps to train, eval variables, modes
    """
    
    # Initialize
    scores = []
    episode = 0
    
    # Set True to print status, lengthens computation
    debug = False
    
    while agent.step <= max_steps:
    
        episode += 1
        
        episode_score, episode_length = train_one_episode(env, agent, selfplay_mode)
        
        if debug:
            print(f'CHECK: complete episode: {episode}, agg steps:{agent.step}, length: {episode_length}, score: {episode_score}')
        
        #agent.episode_lengths.append(episode_length)
        agent.episode_scores.append(episode_score)
        
        if episode % 20 == 0:
            # This score affected by randomness in epsilon
            print(f'PROGRESS: episode: {episode}, step: {agent.step}, {round(agent.step/max_steps, 3)}, epsilon: {agent.epsilon}')
            print(f'PROGRESS: past 20 episode: avg training score: {round(np.mean(agent.episode_scores[-30:]), 3)}, sd: {round(np.std(agent.episode_scores[-30:]), 3)}')

        
        if (episode % eval_freq == 0) and not selfplay_mode: # Evaluate agent performance at interval
            # Evaluate against random policy to track progress
            evaluate_interim(env, agent, n_trials=eval_episodes, render_mode=render_mode)
        

        # NOT DEBUG YET
        # Examine agent with best model to determine if it can become new best model
        # Examine every 30 episode, meaning agent train against same best model during this interval
        if selfplay_mode and (episode % eval_freq == 0): 
            scores = evaluate_bestmodel(env, agent, n_trials=eval_episodes)
            print(f'SELFPLAY-exam: mean_reward achieved: {np.mean(scores)} at step {agent.step}')
            if np.mean(scores) > best_threshold:
                filename = LOGDIR + agent.agent_name + '_history_step' + str(agent.step)
                print(f'SELFPLAY: new best model save to {filename}')
                agent.model.save(filename) # Name the best model after time step
                env.best_model = agent.model # Update the env best model to current agent
                env.best_model_filepath = filename

    return agent # Return agent

"""## Rollout for 1 episode"""

def rollout_random(env, agent, render_mode=False):
    """
    For testing one agent vs random, for one episode
    """
    # Initialize
    state = env.reset()

    done = False
    total_reward = 0
    
    while not done:

        if render_mode:
            env.render()
        
        state = np.reshape(state, (1, 12))
       
        state, reward, done, _ = env.step(action_inverse(agent.act_greedy(state)), action_inverse(agent.act_random()))

        total_reward += reward

    return total_reward

def rollout_agents(env, agent0, agent1, render_mode=False):
    """
    For testing one agent vs other, for one episode
    Agent is incompatible with BaselinePolicy() at the moment, due to input shape problem, use separate function
    """
    # Initialize
    state = env.reset()
    _state = state
    
    done = False
    total_reward = 0
    
    while not done:

        if render_mode:
            env.render()
        
        state = np.reshape(state, (1, 12))
        _state = np.reshape(_state, (1, 12))
        act_values0 = agent0.model.predict(state)
        act_values1 = agent1.model.predict(_state)
        action0 = action_inverse(np.argmax(act_values0[0]))
        action1 = action_inverse(np.argmax(act_values1[0]))
        
        state, reward, done, info = env.step(action0, action1)
        
        state = np.reshape(state, (1, 12))
        _state = info['otherObs'] # Provide observation in policy1 perspective
        _state = np.reshape(_state, (1, 12))
        
        total_reward += reward

    return total_reward

def rollout_baseline(env, agent, render_mode=False):
    """For testing one agent vs baseline, for one episode"""
    # Initialize
    state = env.reset()

    done = False
    total_reward = 0
    
    while not done:

        if render_mode:
            env.render()
        
        state = np.reshape(state, (1, 12))
       
        state, reward, done, _ = env.step(action_inverse(agent.act_greedy(state)))

        total_reward += reward

    return total_reward

def rollout_bestmodel(env, agent, render_mode=False):
    """For testing one agent vs best model under self play env, for one episode"""
    # Initialize
    state = env.reset()
    _state = state
    
    done = False
    total_reward = 0
    
    while not done:

        if render_mode:
            env.render()
        
        state = np.reshape(state, (1, 12))
        _state = np.reshape(_state, (1, 12))
       
        state, reward, done, info = env.step(action_inverse(agent.act_greedy(state)), action_inverse(env.predict(_state)))

        state = np.reshape(state, (1, 12))
        _state = info['otherObs'] # Provide observation in policy1 perspective
        _state = np.reshape(_state, (1, 12))
        
        total_reward += reward

    return total_reward

"""## Evaluate agent"""

def evaluate_interim(env, agent, n_trials=5, init_seed=123, render_mode=False):
    """
    Wrapper for repetitive rollouts using different seeds, playing against random policy
    """
    history = []
    for i in range(n_trials):
        env.seed(seed=init_seed + i)
        episode_score = rollout_random(env, agent, render_mode)
        history.append(episode_score)
    print(f'EVAL INTERIM-Mean total score: {np.round(np.mean(history), 3)} ± {np.round(np.std(history), 3)} over {n_trials} trials, {history}')
    return history

def evaluate_agents(env, agent0, agent1, n_trials=5, init_seed=123, render_mode=False):
    """
    Wrapper for repetitive rollouts using different seeds, playing between two user agents
    """
    history = []
    for i in range(n_trials):
        env.seed(seed=init_seed + i)
        episode_score = rollout_agents(env, agent0, agent1, render_mode)
        history.append(episode_score)
    print(f'EVAL AGENTS-Mean total score: {np.round(np.mean(history), 3)} ± {np.round(np.std(history), 3)} over {n_trials} trials, {history}')
    return history

def evaluate_bestmodel(env, agent, n_trials=5, init_seed=123, render_mode=False):
    """
    Wrapper for repetitive rollouts using different seeds, playing against best model in selfplay
    """
    history = []
    for i in range(n_trials):
        env.seed(seed=init_seed + i)
        episode_score = rollout_bestmodel(env, agent, render_mode)
        history.append(episode_score)
    print(f'EVAL BESTMODEL-Mean total score: {np.round(np.mean(history), 3)} ± {np.round(np.std(history), 3)} over {n_trials} trials, {history}')
    return history

"""## Run_training"""

def run_training(selfplay_mode=False):
    """
    Function to carry out training loop.
    Parameters to be changed here.
    """
    # Training variable
    # Repeat training N times using different seeds
    N = 5
    # Training steps limit
    max_steps = 50000 # int(3e6)
    
    # Evaluation variables
    # Agent will be evaluated by multiple greedy rollouts against random policy during training
    eval_freq = 20 # Evaluate interval (episode) during training, also for selfplay examination
    eval_episodes = 5 # Number of rollouts for each evaluation
    render_mode = False
    
    # Self play parameters
    selfplay_mode = selfplay_mode
    best_threshold = 0.5 # Must achieve a mean score above this to replace prev best self

    LOGDIR = "dqn_test/" # Directory for saving interim and final models
    
    # Stores training result
    trained_agents = []
    
    # Initialize environment
    if selfplay_mode:
        env = SlimeVolleySelfPlayEnv()
    else:
        env = gym.make('SlimeVolley-v0')

    for i in range(N): # Train agent with N different env seeds

        env.seed(seed + i)
        
        # Create agent
        agent_name = 'dqn_selfplay' + str(i) # Agent name for filenaming
        agent = DQN(agent_name=agent_name, 
                    state_space=env.observation_space.shape[0],
                    action_space=2**env.action_space.shape[0],
                    epsilon_decay=0.9995,
                    discount_rate=0.95,
                    learning_rate=0.0001,
                    min_step_to_learn=10000,
                    replay_memory=10000,
                    batch_size=32,
                    target_update_interval=1000, # Steps
                    training_interval=10) # Steps

        start_time = time.process_time()
        
        train_output = train(env, agent, max_steps, eval_freq, eval_episodes, best_threshold, selfplay_mode, render_mode)
        
        end_time = time.process_time()
        print(f'Training for agent {agent_name} completed. Elapsed time: {end_time - start_time}')
        
        trained_agents.append(train_output)
        
        # Save final model
        filename = LOGDIR + agent.agent_name + '_final_step' + str(agent.step)
        agent.model.save(filename) # Name the best model after time step
        
    return trained_agents

"""# Run training"""

if __name__ == '__main__':
    trained_agents = run_training(selfplay_mode=True)
    #trained_agents = run_training(selfplay_mode=False) # Uncomment to run without selfplay
