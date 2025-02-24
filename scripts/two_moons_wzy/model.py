"""Define the model for the two moons toy problem."""
import pyro
import pyro.distributions as dist
import pyro.distributions
import torch


def generate_two_moons_data(n, device, failure=False, sigma=0.1):
    """Generate two moons data.

    Args:
        n (int): Number of samples to generate.
        device (torch.device): Device to use.
        failure (bool): Whether to generate failure data.
    """
    theta = torch.pi * torch.rand(n).to(device)
    if failure:
        theta += torch.pi

    x = torch.stack(
        (
            torch.cos(theta) - 1 / 2,
            torch.sin(theta) - 1 / 4,
        ),
        axis=-1,
    )
    if failure:
        x += torch.tensor([1.0, 0.5]).to(device)

    return torch.normal(x, sigma)


def generate_two_moons_data_hierarchical(
        n, device, sigma=0.1, w_obs=None, z_obs=None, theta_obs=None, failure_obs=None,
        failure=False, nominal=False,
    ):
    """Generate two moons data.

    Args:
        n (int): Number of samples to generate.
        device (torch.device): Device to use.
        failure (bool): Whether to generate failure data.
    """

    if w_obs is None:
        unit = torch.rand(n).to(device)
        k = .51
        if failure:
            w = 1 - k * unit
            # print(w)
        elif nominal:
            w = k * unit
        else:
            w = torch.rand(n).to(device)
    else:
        w = w_obs

    z = w > .5 if failure_obs is None else failure_obs > .5
    # z = w > .5

    if theta_obs is None:
        theta = torch.pi * torch.rand(n).to(device)
        theta[z] += torch.pi
    else:
        theta = theta_obs


    y = torch.stack(
        (
            torch.cos(theta) - 1 / 2,
            torch.sin(theta) - 1 / 4,
        ),
        axis=-1,
    )
        
    y[z] += (torch.tensor([1.0, 0.5]).to(device))

    if z_obs is not None:
        y = z_obs

    y = torch.normal(y, sigma)

    return y.cpu(), w.cpu()



def two_moons_model(n, device, obs=None):
    """Define noisy observation for the two moons dataset.

    This function doesn't actually create the data, just models the observation.
    """
    with pyro.plate("data", n):
        x = pyro.sample(
            "x",
            dist.Normal(
                torch.zeros(2, device=device),
                5 * torch.ones(2, device=device),
            ).to_event(1),
        )

        noisy_obs = pyro.sample(
            "obs",
            dist.Normal(
                x,
                torch.tensor([0.1, 0.1]).to(device),
            ).to_event(1),
            obs=obs,
        )

    return noisy_obs


def two_moons_w_z_model(n, device, obs=None):

    with pyro.plate("data", n):
        w = pyro.sample(
            "w", 
            dist.Beta(
                torch.tensor(1.0, device=device),
                torch.tensor(1.0, device=device),
            )
        )

        z = pyro.sample(
            "z",
            dist.RelaxedBernoulliStraightThrough(
                temperature=torch.tensor(0.1, device=device),
                probs=w,
            ),
            obs=obs
        )

    return z


def two_moons_z_y_model(n, device, obs=None):

    with pyro.plate("data", n):
        z = pyro.sample(
            "z",
            dist.Beta(
                torch.tensor(1.0, device=device),
                torch.tensor(1.0, device=device),
            ),
        )

        failure = torch.tensor(1.0, device=device) * (z > .5)

        theta = pyro.sample(
            "theta",
            dist.Beta(
                torch.tensor(1.0, device=device),
                torch.tensor(1.0, device=device),
            ),
        )

        theta = (theta + failure) * torch.pi

        y_val = torch.stack(
            (
                torch.cos(theta) - 1 / 2,
                torch.sin(theta) - 1 / 4,
            ),
            axis=-1,
        )
        
        y_val += (torch.tensor([1.0, 0.5]).to(device)) * failure.unsqueeze(-1)

        y = pyro.sample(
            "y",
            dist.Normal(
                y_val,
                torch.tensor([0.1, 0.1]).to(device),
            ).to_event(1),
            obs=obs,
        )

    return y


def two_moons_w_z_y_model(n, device, w_obs=None, y_obs=None, theta_obs=None, failure_obs=None):

    with pyro.plate("data", n):
         
        if w_obs is not None:
            w = pyro.deterministic(
                "w", 
                w_obs
            )
            # w = pyro.sample(
            #     "w", 
            #     dist.Normal(
            #         w_obs, .05
            #     ),
            #     obs=w_obs
            # )
        else:
            w = pyro.sample(
                "w",
                dist.Beta(
                    torch.tensor(1.0, device=device),
                    torch.tensor(1.0, device=device)
                )
            )
        
        # print(w)
        w_s = torch.zeros(w.shape, device=device)
        w_s[w >  .5] = 1.0
        w_s[w <= .5] = 0.0
        # w_s = w

        failure = pyro.sample(
            "failure",
            dist.RelaxedBernoulliStraightThrough(
                temperature=torch.tensor(0.01, device=device),
                probs=w_s,
            ),
            obs=failure_obs
        )

        loc = failure * torch.pi

        theta = pyro.sample(
            "theta",
            # dist.AffineBeta(
            #     torch.tensor(1.0, device=device),
            #     torch.tensor(1.0, device=device),
            #     loc,
            #     torch.pi
            # ),
            dist.Beta(
                torch.tensor(1.0, device=device),
                torch.tensor(1.0, device=device)
            ),
            obs=theta_obs
        )

        theta = theta * torch.pi + loc

        # print(loc)
        # print(theta)

        # print(
        #     loc.min().item(), 
        #     loc.max().item(), 
        #     theta.min().item(),
        #     theta.max().item(),
        # )

        # print(f'failure: {failure.shape}')
        # print(f'theta: {theta.shape}')

        z_x = (torch.cos(theta) - 1/2)
        z_y = (torch.sin(theta) - 1/4)

        z = torch.stack(
            (
                z_x, z_y,
            ),
            axis=-1,
        )

        # # print(z.shape)
        # f = torch.zeros(*theta.shape)
        # # print(f.shape)
        # f[theta <  torch.pi] = 0.0
        # f[theta >= torch.pi] = 1.0
        # f = f.reshape(*f.shape,1).expand(*f.shape,2)
        f = failure.reshape(*failure.shape,1).expand(*failure.shape,2)
        offset = pyro.param("offset", torch.tensor([1.0, 0.5], device=device), event_dim=1).reshape(-1,2)
        # offset = offset.reshape()
        # print(f'offset: {offset.shape}')

        z += f * offset

        y = pyro.sample(
            "y",
            dist.Normal(
                z,
                torch.tensor([0.1, 0.1]).to(device),
            ).to_event(1),
            obs=y_obs,
        )

    return y


def two_moons_wzy_model(device, states, **kwargs):

    obs_none = kwargs.get("obs_none", False)

    w = pyro.sample(
        "w",
        dist.Beta(
            torch.tensor(1.0, device=device),
            torch.tensor(1.0, device=device)
        )
    )
    
    # print(w)
    w_s = torch.zeros(w.shape, device=device)
    w_s[w >  .5] = 1.0
    w_s[w <= .5] = 0.0

    failure = pyro.sample(
        "failure",
        dist.RelaxedBernoulliStraightThrough(
            temperature=torch.tensor(0.1, device=device),
            probs=w_s,
        ),
    )

    loc = failure * torch.pi

    theta = pyro.sample(
        "base_theta",
        dist.Beta(
            torch.tensor(1.0, device=device),
            torch.tensor(1.0, device=device)
        ),
    )

    theta = theta * torch.pi + loc

    z_x = (torch.cos(theta) - 1/2)
    z_y = (torch.sin(theta) - 1/4)

    z = torch.stack(
        (z_x, z_y), axis=-1
    )

    f = failure.reshape(*failure.shape,1).expand(*failure.shape,2)
    offset = pyro.param("offset", torch.tensor([1.0, 0.5], device=device), event_dim=1)#.reshape(-1,2)

    # print(f, offset)

    z += f * offset

    z = pyro.deterministic(
        "z", z
    )

    # with pyro.plate("data", n):
    for day_ind in pyro.markov(range(len(states)), history=1):
        var_prefix = f'{day_ind}_'

        y = pyro.sample(
            var_prefix + "y",
            dist.Normal(
                z,
                torch.tensor([0.1, 0.1]).to(device),
            ).to_event(1),
            obs=states[day_ind] if not obs_none else None,
        )

    return y

def two_moons_wzy_model_even_simpler(device, states, **kwargs):

    obs_none = kwargs.get("obs_none", False)

    w = pyro.sample(
        "w",
        dist.Beta(
            torch.tensor(1.0, device=device),
            torch.tensor(1.0, device=device)
        )
    )
    
    # print(w)
    w_s = torch.zeros(w.shape, device=device)
    w_s[w >  .5] = 1.0
    w_s[w <= .5] = 0.0

    failure = pyro.sample(
        "failure",
        dist.RelaxedBernoulliStraightThrough(
            temperature=torch.tensor(0.1, device=device),
            probs=w_s,
        ),
    )

    loc = failure * 2.0 - 1.0

    z_x = loc 
    z_y = loc

    z = torch.stack(
        (z_x, z_y), axis=-1
    )

    z = pyro.deterministic(
        "z", z
    )

    # with pyro.plate("data", n):
    for day_ind in pyro.markov(range(len(states)), history=1):
        var_prefix = f'{day_ind}_'

        y = pyro.sample(
            var_prefix + "y",
            dist.Normal(
                z,
                torch.tensor([0.1, 0.1]).to(device),
            ).to_event(1),
            obs=states[day_ind] if not obs_none else None,
        )

    return y


def two_moons_wzy_model_plated(n, device, w_obs=None, y_obs=None):

    with pyro.plate("data", n):
         
        if w_obs is not None:
            w = pyro.deterministic(
                "w", 
                w_obs
            )
        else:
            w = pyro.sample(
                "w",
                dist.Beta(
                    torch.tensor(1.0, device=device),
                    torch.tensor(1.0, device=device)
                )
            )
        
        w_s = torch.zeros(w.shape, device=device)
        w_s[w >  .5] = 1.0
        w_s[w <= .5] = 0.0

        # failure = pyro.sample(
        #     "failure",
        #     dist.RelaxedBernoulliStraightThrough(
        #         temperature=torch.tensor(0.01, device=device),
        #         probs=w_s,
        #     ).mask(False),
        # )

        failure = (
            dist.RelaxedBernoulliStraightThrough(
                temperature=torch.tensor(0.01, device=device),
                probs=w_s,
            ).rsample((n,))
        )

        loc = failure * torch.pi

        # theta = pyro.sample(
        #     "theta",
        #     dist.Beta(
        #         torch.tensor(1.0, device=device),
        #         torch.tensor(1.0, device=device)
        #     ).mask(False),
        # )
        theta = (
            dist.Beta(
                torch.tensor(1.0, device=device),
                torch.tensor(1.0, device=device)
            ).rsample((n,))
        )

        theta = theta * torch.pi + loc

        z_x = (torch.cos(theta) - 1/2)
        z_y = (torch.sin(theta) - 1/4)

        z = torch.stack(
            (
                z_x, z_y,
            ),
            axis=-1,
        )

        f = failure.reshape(*failure.shape,1).expand(*failure.shape,2)
        offset = pyro.param("offset", torch.tensor([1.0, 0.5], device=device), event_dim=1).reshape(-1,2)

        z += f * offset

        pyro.deterministic("z", z)

        y = pyro.sample(
            "y",
            dist.Normal(
                z,
                torch.tensor([0.1, 0.1]).to(device),
            ).to_event(1),
            obs=y_obs,
        )

    return y



def generate_two_moons_data_using_model(n, m, device, **kwargs):

    w = torch.rand(n).to(device)
    if kwargs.get("failure_only", False):
        w = 0.5 + 0.5 * w
    elif kwargs.get("nominal_only", False):
        w = 0.5 * w
        
    conditioning_dict = {}
    states = [None] * m

    w_list = [w[i] for i in range(len(w))]
    y_list = []
    states_list = []
    z_list = []

    if kwargs.get("even_simpler", False):
        model = two_moons_wzy_model_even_simpler
    else:
        model = two_moons_wzy_model

    for i in range(n):
        conditioning_dict = {'w': w_list[i]}

        model_trace = pyro.poutine.trace(
            pyro.poutine.condition(model, data=conditioning_dict)
        ).get_trace(
            device=device,
            states=states,
            obs_none=True,
        )
        states = [
            model_trace.nodes[f'{day_ind}_y']['value'].detach()
            for day_ind in range(m)
        ]
        states_list.append(states)
        y = torch.stack(states, axis=0)
        y_list.append(y)

        z = model_trace.nodes[f'z']['value'].detach()
        z_list.append(z)

        # print(y.mean(axis=0), z_list[i])


    return_states = kwargs.get("return_states", False)
    return_z = kwargs.get("return_z", False)

    ret = [y_list, w_list]
    if return_states:
        ret.append(states_list)
    if return_z:
        ret.append(z_list)

    return tuple(ret)


def generate_two_moons_data_using_model_plated(n, device, **kwargs):

    w = torch.rand(n).to(device)
    if kwargs.get("failure_only", False):
        w = 0.5 + 0.5 * w
    elif kwargs.get("nominal_only", False):
        w = 0.5 * w
        
    # if kwargs.get("even_simpler", False):
    #     model = two_moons_wzy_model_even_simpler
    # else:
    #     model = two_moons_wzy_model
    model = two_moons_wzy_model_plated

    conditioning_dict = {'w': w}

    model_trace = pyro.poutine.trace(
        pyro.poutine.condition(model, data=conditioning_dict)
    ).get_trace(
        n=n,
        device=device,
    )
    y = model_trace.nodes['y']['value'].detach()
    z = model_trace.nodes['z']['value'].detach()

    return_z = kwargs.get("return_z", False)

    ret = [y, w]
    if return_z:
        ret.append(z)

    return tuple(ret)



def test():
    import matplotlib.pyplot as plt

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # y, w = generate_two_moons_data_hierarchical(1000, device)

    y_list, w_list = generate_two_moons_data_using_model(100, 10, device)
    # y_list, w_list = generate_two_moons_data_using_model(100, 10, device, failure_only=True)
    # y_list, w_list = generate_two_moons_data_using_model(100, 10, device, nominal_only=True)

    plt.figure(figsize=(4, 4))
    for y, w in zip(y_list, w_list):
        c = 'r' if w > .5 else 'b'
        samples = y
        plt.scatter(*samples.T, s=1, c=c, cmap="bwr")
    # Turn off axis ticks
    plt.xticks([])
    plt.yticks([])
    plt.axis("off")
    plt.ylim([-1.1, 1.1])
    plt.xlim([-1.7, 1.7])
    # Equal aspect
    plt.gca().set_aspect("equal")
    plt.show()

if __name__ == "__main__":
    test()
