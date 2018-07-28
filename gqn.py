import torch
import torch.nn as nn
from torch.distributions import Normal

from representation import RepresentationNetwork
from generator import GeneratorNetwork


def _transform_viewpoint(x, v):
        """
        Transforms the viewpoint vector into a consistent
        representation and merges batch and M dimensions
        of the data.
        """
        w, z = torch.split(v, 3, dim=-1)
        y, p = torch.split(z, 1, dim=-1)

        # position, [yaw, pitch]
        view_vector = [w, torch.cos(y), torch.sin(y), torch.cos(p), torch.sin(p)]
        v_hat = torch.cat(view_vector, dim=-1)

        # Reshape along batch dimension
        _, _, *x_dims = x.size()
        _, _, *v_dims = v_hat.size()

        x = x.view((-1, *x_dims))
        v_hat = v_hat.view((-1, *v_dims))

        return x, v_hat


class GenerativeQueryNetwork(nn.Module):
    """
    Generative Query Network (GQN) as described
    in "Neural scene representation and rendering"
    [Eslami 2018].

    :param x_dim: number of channels in input
    :param v_dim: dimensions of viewpoint
    :param r_dim: dimensions of representation
    :param z_dim: latent channels
    :param h_dim: hidden channels in LSTM
    :param L: Number of refinements of density
    """
    def __init__(self, x_dim, v_dim, r_dim, h_dim, z_dim, L=12):
        super(GenerativeQueryNetwork, self).__init__()
        self.r_dim = r_dim

        self.generator = GeneratorNetwork(x_dim, v_dim, r_dim, z_dim, h_dim, L)
        self.representation = RepresentationNetwork(x_dim, v_dim + 2)

    def forward(self, images, viewpoints, sigma):
        """
        Forward through the GQN.

        :param images: batch of images [b, m, c, h, w]
        :param viewpoints: batch of viewpoints for image [b, m, k]
        :param sigma: pixel variance
        """
        # Number of context datapoints to use for representation
        m, batch_size, *_ = viewpoints.size()
        m = m - 1

        # Split data into representation and query
        x, v = images[:m], viewpoints[:m]
        x_q, v_q = images[m], viewpoints[m]

        # Transform data for representation
        x, v_hat = _transform_viewpoint(x, v)

        # representation generated from input images
        # and corresponding viewpoints.
        phi = self.representation(x, v_hat)
        phi = phi.view(m, batch_size, -1)

        # sum over representations
        r = torch.sum(phi, dim=0)

        # Inference q(z|x, v, r) (1.5)
        # Prior π(z|v, r)
        # Generator g(x|z, v, r) (1.4)
        x_mu, kl = self.generator(x_q, v_q, r)

        # Draw a sample from generative density
        x_sample = Normal(x_mu, sigma).rsample()

        # ELBO is given by log likelihood of data
        # (reconstruction error) E(x_sample, x) and
        # KL-divergence between conditional prior
        # and variational distribution
        return [x_sample, x_q, r, kl]

    def sample(self, x_shape, v, r, sigma):
        x_mu = self.generator.sample(x_shape, v, r)
        x_sample = Normal(x_mu, sigma).sample()
        return x_sample