from select import epoll

import numpy as np
from mushroom_rl.core import Serializable


class ReplayMemory(Serializable):
    """
    This class implements function to manage a replay memory as the one used in
    "Human-Level Control Through Deep Reinforcement Learning" by Mnih V. et al..

    """

    def __init__(self, initial_size, max_size):
        """
        Constructor.

        Args:
            initial_size (int): initial number of elements in the replay memory;
            max_size (int): maximum number of elements that the replay memory
                can contain.

        """
        self._initial_size = initial_size
        self._max_size = max_size

        self.reset()

        self._add_save_attr(
            _initial_size='pickle',
            _max_size='pickle',
            _idx='pickle!',
            _full='pickle!',
            _states='pickle!',
            _actions='pickle!',
            _rewards='pickle!',
            _next_states='pickle!',
            _absorbing='pickle!',
            _last='pickle!'
        )

    def add(self, dataset):
        """
        Add elements to the replay memory.

        Args:
            dataset (list): list of elements to add to the replay memory.

        """
        for i in range(len(dataset)):
            self._states[self._idx] = dataset[i][0]
            self._actions[self._idx] = dataset[i][1]
            self._rewards[self._idx] = dataset[i][2]
            self._next_states[self._idx] = dataset[i][3]
            self._absorbing[self._idx] = dataset[i][4]
            self._last[self._idx] = dataset[i][5]

            self._idx += 1
            if self._idx == self._max_size:
                self._full = True
                self._idx = 0

    def get(self, n_samples):
        """
        Returns the provided number of states from the replay memory.

        Args:
            n_samples (int): the number of samples to return.

        Returns:
            The requested number of samples.

        """
        s = list()
        a = list()
        r = list()
        ss = list()
        ab = list()
        last = list()
        for i in np.random.randint(self.size, size=n_samples):
            s.append(np.array(self._states[i]))
            a.append(self._actions[i])
            r.append(self._rewards[i])
            ss.append(np.array(self._next_states[i]))
            ab.append(self._absorbing[i])
            last.append(self._last[i])

        return np.array(s), np.array(a), np.array(r), np.array(ss), \
               np.array(ab), np.array(last)

    def reset(self):
        """
        Reset the replay memory.

        """
        self._idx = 0
        self._full = False
        self._states = [None for _ in range(self._max_size)]
        self._actions = [None for _ in range(self._max_size)]
        self._rewards = [None for _ in range(self._max_size)]
        self._next_states = [None for _ in range(self._max_size)]
        self._absorbing = [None for _ in range(self._max_size)]
        self._last = [None for _ in range(self._max_size)]

    @property
    def initialized(self):
        """
        Returns:
            Whether the replay memory has reached the number of elements that
            allows it to be used.

        """
        return self.size > self._initial_size

    @property
    def size(self):
        """
        Returns:
            The number of elements contained in the replay memory.

        """
        return self._idx if not self._full else self._max_size

    def _post_load(self):
        if self._full is None:
            self.reset()


class SumTree(object):
    """
    This class implements a sum tree data structure.
    This is used, for instance, by ``PrioritizedReplayMemory``.

    """

    def __init__(self, max_size):
        """
        Constructor.

        Args:
            max_size (int): maximum size of the tree.

        """
        self._max_size = max_size
        self._tree = np.zeros(2 * max_size - 1)
        self._data = [None for _ in range(max_size)]
        self._idx = 0
        self._full = False

    def add(self, dataset, priority):
        """
        Add elements to the tree.

        Args:
            dataset (list): list of elements to add to the tree;
            p (np.ndarray): priority of each sample in the dataset.

        """
        for d, p in zip(dataset, priority):
            idx = self._idx + self._max_size - 1

            self._data[self._idx] = d
            self.update([idx], [p])

            self._idx += 1
            if self._idx == self._max_size:
                self._idx = 0
                self._full = True

    def get(self, s):
        """
        Returns the provided number of states from the replay memory.

        Args:
            s (float): the value of the samples to return.

        Returns:
            The requested sample.

        """
        idx = self._retrieve(s, 0)
        data_idx = idx - self._max_size + 1

        return idx, self._tree[idx], self._data[data_idx]

    def update(self, idx, priorities):
        """
        Update the priority of the sample at the provided index in the dataset.

        Args:
            idx (np.ndarray): indexes of the transitions in the dataset;
            priorities (np.ndarray): priorities of the transitions.

        """
        for i, p in zip(idx, priorities):
            delta = p - self._tree[i]

            self._tree[i] = p
            self._propagate(delta, i)

    def _propagate(self, delta, idx):
        parent_idx = (idx - 1) // 2

        self._tree[parent_idx] += delta

        if parent_idx != 0:
            self._propagate(delta, parent_idx)

    def _retrieve(self, s, idx):
        left = 2 * idx + 1
        right = left + 1

        if left >= len(self._tree):
            return idx

        if self._tree[left] == self._tree[right]:
            return self._retrieve(s, np.random.choice([left, right]))

        if s <= self._tree[left]:
            return self._retrieve(s, left)
        else:
            return self._retrieve(s - self._tree[left], right)

    @property
    def size(self):
        """
        Returns:
            The current size of the tree.

        """
        return self._idx if not self._full else self._max_size

    @property
    def max_p(self):
        """
        Returns:
            The maximum priority among the ones in the tree.

        """
        return self._tree[-self._max_size:].max()

    @property
    def total_p(self):
        """
        Returns:
            The sum of the priorities in the tree, i.e. the value of the root
            node.

        """
        return self._tree[0]


class PrioritizedReplayMemory(Serializable):
    """
    This class implements function to manage a prioritized replay memory as the
    one used in "Prioritized Experience Replay" by Schaul et al., 2015.

    """

    def __init__(self, initial_size, max_size, alpha, beta, epsilon=.01):
        """
        Constructor.

        Args:
            initial_size (int): initial number of elements in the replay
                memory;
            max_size (int): maximum number of elements that the replay memory
                can contain;
            alpha (float): prioritization coefficient;
            beta (float): importance sampling coefficient;
            epsilon (float, .01): small value to avoid zero probabilities.

        """
        self._initial_size = initial_size
        self._max_size = max_size
        self._alpha = alpha
        self._beta = beta
        self._epsilon = epsilon

        self._tree = SumTree(max_size)

        self._add_save_attr(
            _initial_size='pickle',
            _max_size='pickle',
            _alpha='pickle',
            _beta='pickle',
            _epsilon='pickle',
            _tree='pickle!'
        )

    def add(self, dataset, p):
        """
        Add elements to the replay memory.

        Args:
            dataset (list): list of elements to add to the replay memory;
            p (np.ndarray): priority of each sample in the dataset.

        """
        self._tree.add(dataset, p)

    def get(self, n_samples):
        """
        Returns the provided number of states from the replay memory.

        Args:
            n_samples (int): the number of samples to return.

        Returns:
            The requested number of samples.

        """
        states = [None for _ in range(n_samples)]
        actions = [None for _ in range(n_samples)]
        rewards = [None for _ in range(n_samples)]
        next_states = [None for _ in range(n_samples)]
        absorbing = [None for _ in range(n_samples)]
        last = [None for _ in range(n_samples)]

        idxs = np.zeros(n_samples, dtype=np.int)
        priorities = np.zeros(n_samples)

        total_p = self._tree.total_p
        segment = total_p / n_samples

        a = np.arange(n_samples) * segment
        b = np.arange(1, n_samples + 1) * segment
        samples = np.random.uniform(a, b)
        for i, s in enumerate(samples):
            idx, p, data = self._tree.get(s)

            idxs[i] = idx
            priorities[i] = p
            states[i], actions[i], rewards[i], next_states[i], absorbing[i], \
            last[i] = data
            states[i] = np.array(states[i])
            next_states[i] = np.array(next_states[i])

        sampling_probabilities = priorities / self._tree.total_p
        is_weight = (self._tree.size * sampling_probabilities) ** -self._beta()
        is_weight /= is_weight.max()

        return np.array(states), np.array(actions), np.array(rewards), \
               np.array(next_states), np.array(absorbing), np.array(last), \
               idxs, is_weight

    def update(self, error, idx):
        """
        Update the priority of the sample at the provided index in the dataset.

        Args:
            error (np.ndarray): errors to consider to compute the priorities;
            idx (np.ndarray): indexes of the transitions in the dataset.

        """
        p = self._get_priority(error)
        self._tree.update(idx, p)

    def _get_priority(self, error):
        return (np.abs(error) + self._epsilon) ** self._alpha

    @property
    def initialized(self):
        """
        Returns:
            Whether the replay memory has reached the number of elements that
            allows it to be used.

        """
        return self._tree.size > self._initial_size

    @property
    def max_priority(self):
        """
        Returns:
            The maximum value of priority inside the replay memory.

        """
        return self._tree.max_p if self.initialized else 1.

    def _post_load(self):
        if self._tree is None:
            self._tree = SumTree(self._max_size)


# todo sequential updates
class SequentialReplayMemory(Serializable):
    """
    This class implements function to manage a replay memory as the one used in
    "Deep Recurrent Q-Learning for Partially Observable MDPs"
    by Hausknecht, M. et al..

    """

    def __init__(self, initial_size, max_size, unroll_steps,
                 sequential_updates=False):
        """
        Constructor.

        Args:
            initial_size (int): initial number of elements in the replay memory
            max_size (int): maximum number of elements that the replay memory
                can contain.
            unroll_steps (int): number of elements per sample; also the minimum
                length for an episode to be stored.
            sequential_updates (bool): if True whole episodes are sampled
                (corresponds to Sequential updates in the paper) otherwise
                random parts of the episode will be sampled

        """
        self._initial_size = initial_size
        self._max_size = max_size
        self._unroll_steps = unroll_steps
        # todo
        self._sequential_updates = sequential_updates and False

        # length of each episode
        self._lengths = list()

        self._size = 0
        self._states = list()
        self._actions = list()
        self._rewards = list()
        self._next_states = list()
        self._absorbing = list()
        self._last = list()

        # save unfinished episode to collect the missing steps
        # in order to only store full episodes
        self.unfinished_episode = list()

        self._add_save_attr(
            _initial_size='primitive',
            _max_size='pickle',
            _size='pickle',
            _unroll_steps='pickle!',
            _full='pickle!',
            _states='pickle!',
            _actions='pickle!',
            _rewards='pickle!',
            _next_states='pickle!',
            _absorbing='pickle!',
            _last='pickle!'
        )

    def add(self, dataset):
        """
        Add full episodes to the replay memory.

        Args:
            dataset (list): episode to add to the replay memory.

        Returns:
            Number of episodes that have been added

        """
        # split dataset into episodes
        episodes, self.unfinished_episode = \
            self._split_dataset(self.unfinished_episode + dataset)

        added = 0
        # add every episode one by one
        for episode in episodes:

            # only store if the episode is long enough but not too long
            if self._unroll_steps <= len(episode) < self._max_size:

                s = list()
                a = list()
                r = list()
                ss = list()
                ab = list()
                last = list()

                for i in range(len(episode)):
                    s.append(episode[i][0])
                    a.append(episode[i][1])
                    r.append(episode[i][2])
                    ss.append(episode[i][3])
                    ab.append(episode[i][4])
                    last.append(episode[i][5])

                # add episode to replay buffer
                self._states.append(s)
                self._actions.append(a)
                self._rewards.append(r)
                self._next_states.append(ss)
                self._absorbing.append(ab)
                self._last.append(last)

                self._size += len(episode)
                self._lengths.append(len(episode))
                while self._size > self._max_size:
                    # remove oldest episode
                    self._size -= len(self._states.pop(0))
                    self._actions.pop(0)
                    self._rewards.pop(0)
                    self._next_states.pop(0)
                    self._absorbing.pop(0)
                    self._last.pop(0)
                    self._lengths.pop(0)

                added += 1

        return added

    def get(self, batch_size):
        """
        Returns the provided number of samples from the replay memory.

        Args:
            batch_size (int): the number of samples to return.

        Returns:
            The samples as n_samples x unroll_steps x sample shape
                todo or a whole episode if self.sequential_updates is True.

        """
        assert batch_size <= self._initial_size, \
            "The batch size should be smaller than the initial size."

        s = list()
        a = list()
        r = list()
        ss = list()
        ab = list()
        last = list()

        # randomly selected episodes
        eps = np.random.randint(len(self._states), size=batch_size)

        # randomly selected start indices for EVERY episode
        idx = np.random.randint(0, np.array(
            self._lengths) - self._unroll_steps + 1)

        for _ in range(self._unroll_steps):

            s_ep = list()
            a_ep = list()
            r_ep = list()
            ss_ep = list()
            ab_ep = list()
            last_ep = list()

            for ep in eps:
                s_ep.append(np.array(self._states[ep][idx[ep]]))
                a_ep.append(self._actions[ep][idx[ep]])
                r_ep.append(self._rewards[ep][idx[ep]])
                ss_ep.append(np.array(self._next_states[ep][idx[ep]]))
                ab_ep.append(self._absorbing[ep][idx[ep]])
                last_ep.append(self._last[ep][idx[ep]])

            s.append(np.array(s_ep))
            a.append(np.array(a_ep))
            r.append(np.array(r_ep))
            ss.append(np.array(ss_ep))
            ab.append(np.array(ab_ep))
            last.append(np.array(last_ep))

            idx += 1

        return np.array(s), np.array(a), np.array(r), np.array(ss), \
               np.array(ab), np.array(last)

    def reset(self):
        """
        Reset the replay memory.

        """
        self._size = 0
        self._states = list()
        self._actions = list()
        self._rewards = list()
        self._next_states = list()
        self._absorbing = list()
        self._last = list()
        self._lengths = list()

    @property
    def initialized(self):
        """
        Returns:
            Whether the replay memory has reached the number of elements that
            allows it to be used.

        """
        return self._size > self._initial_size

    @property
    def size(self):
        """
        Returns:
            The number of elements contained in the replay memory.

        """
        return self._size

    @staticmethod
    def _split_dataset(dataset):
        """
        Returns:
            A list of full episodes in the dataset and the unfinished episode

        """
        # split data into episodes based on absorbing flag
        indices = np.where(np.array(dataset, dtype=object)[:, -2])[0].tolist()

        # calculate start and end values from indices
        args = (0,) + tuple(data + 1 for data in indices)

        episodes = []
        end = 0
        for start, end in zip(args, args[1:]):
            episodes.append(dataset[start:end])

        return episodes, dataset[end:len(dataset)]

    def get_batch_first(self, n_samples):
        """
        Returns the provided number of samples from the replay memory.

        Args:
            n_samples (int): the number of samples to return.

        Returns:
            The samples as n_samples x unroll_steps x sample shape
                todo or a whole episode if self.sequential_updates is True.

        """
        assert n_samples <= self._initial_size, \
            "n_samples should be smaller than the initial size"

        s = list()
        a = list()
        r = list()
        ss = list()
        ab = list()
        last = list()

        for ep in np.random.randint(len(self._states), size=n_samples):
            ep_len = len(self._last[ep])
            start = np.random.randint(0, ep_len - self._unroll_steps + 1)
            end = start + self._unroll_steps

            s_ep = list()
            a_ep = list()
            r_ep = list()
            ss_ep = list()
            ab_ep = list()
            last_ep = list()

            for i in range(start, end):
                s_ep.append(np.array(self._states[ep][i]))
                a_ep.append(self._actions[ep][i])
                r_ep.append(self._rewards[ep][i])
                ss_ep.append(np.array(self._next_states[ep][i]))
                ab_ep.append(self._absorbing[ep][i])
                last_ep.append(self._last[ep][i])

            s.append(np.array(s_ep))
            a.append(np.array(a_ep))
            r.append(np.array(r_ep))
            ss.append(np.array(ss_ep))
            ab.append(np.array(ab_ep))
            last.append(np.array(last_ep))

        return np.array(s), np.array(a), np.array(r), np.array(ss), \
               np.array(ab), np.array(last)
