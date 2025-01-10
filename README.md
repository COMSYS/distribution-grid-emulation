# Distribution Grid Emulation incl. Topology

## Description

This repository contains the code from our study on evaluating transport protocols, particularly MPTCP, in the context of reliable communication within energy distribution grids.

```bibtex
@inproceedings{2025_fink_mptcp-eval,
    author = {Fink, Ina Berenice and Ferlemann, Lennart and Dahlmanns, Markus and Thimm, Christian and Wehrle, Klaus},
    title = {{Emulating and Evaluating Transport Layer Protocols for Resilient Communication in Smart Grids}},
    booktitle = {Proceedings of the 2025 IEEE/IFIP Network Operations and Management Symposium (NOMS '25), May 12-16, 2025, Honolulu, HI, USA},
    year = {2025},
    publisher = {IEEE},
}
```

## Simulation setup

Install rettij from https://gitlab.com/frihsb/rettij

Enter our project directory.

### Generate topology

`<topology.yaml>` and `<topology-ips.txt>` are the output files.

```bash
python3 topology-generator/generator.py <topology.yaml> <topology-ips.txt>
```

### Starting rettij

1.  Run the following command, where `<topology.yaml>` is a topology that has been generated with the topology generator. Note that this can take about an hour for large topologies such as the one provided.

    ```bash
    rettij -t <topology.yaml> --components custom-components/
    ```

3.  Set up the rettij interfaces, the necessary commands will be output by rettij while setting up the simulation.
    It might be necessary to delete old interfaces from a preceding simulation run using the displayed commands beforehand.

4.  If desired, connect the rettij interfaces for control center computer (rettij.pc) and RTU (rettij.rtu) to the external devices using network bridges.
    For example for the bridges br0 and br1:

    ```bash
    sudo ip addr del 10.100.101.2/24 dev rettij.pc
    sudo ip addr del 10.100.102.2/24 dev rettij.rtu
    sudo ip link set rettij.pc master br0
    sudo ip link set rettij.rtu master br1
    ```

Note that we applied the following changes to k3s to successfully run rettij with our topology. 

### Modifications to Kubernetes (k3s)

*   The root directory for kubelet has to be changed, because the root file system was too full, and an additional partition was created.
    This change was done in the file `/etc/rancher/k3s/config.yaml`.

    ```yaml
    kubelet-arg:
    - "root-dir=/data/kubelet"
    ```

*   The maximum number of pods had to be raised because of the size of our topology.
    This change was done in the file `/etc/rancher/k3s/config.yaml` and the file `/etc/rancher/k3s/kubelet.yaml` had to be added.

    ```yaml
    kubelet-arg:
    - "config=/etc/rancher/k3s/kubelet.yaml"
    ```

    ```yaml
    apiVersion: kubelet.config.k8s.io/v1beta1
    kind: KubeletConfiguration
    maxPods: 1000
    ```

*   The size of the default network for the pods had to be increased.
    This change was done in the files `/etc/rancher/k3s/config.yaml` and `/etc/rancher/k3s/kubelet.yaml` respectively.

    ```yaml
    cluster-cidr: "10.44.0.0/16"
    ```

    ```yaml
    podCIDR: "10.44.0.0/16"
    ```

*   The Kubernetes node needs to be exported, modified, deleted and re-created, to reflect the changed network.

    ```bash
    kubectl get node <node> -o yaml ><node.yaml>
    # adjust podCIDR and podCIDRs
    vim <node.yaml>
    kubectl delete node <node>
    kubectl create -f <node.yaml>
    ```
    
