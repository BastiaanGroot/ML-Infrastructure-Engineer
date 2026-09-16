# Take-Home Assignment: ML Infrastructure Engineer

Thank you for applying for the ML Infrastructure Engineer role! For your take-home assignment, you are asked to complete the following exercise before your demo day. You will perform a short presentation during the demo day and provide the code used to complete the assignment.

## Overview

You have just received some news about a potential customer. Before committing to reserve GPU capacity at Nebius (they are looking to reserve 512 H100 GPUs for an initial duration of 6 months), they would like to do some testing on our platform during a PoC (Proof-of-Concept) stage.

A small VC-funded startup wants to train an LLM and host the model on their own inferencing server. You had a brief call with their team who will be running the PoC. They are mostly ML Engineers without extensive Cloud/Infrastructure expertise. They want a PoC on our platform to validate performance and reliability.

## Exercise

Customers are provided a cluster with their requested capacity. It is essential before running any workload on the cluster to ensure the cluster is configured to the expected performance. Build a lightweight, portable container that validates the cluster's capabilities for a training/inference job. Include the results as part of your documentation and the build code in your repository.

Once the cluster is validated, choose one of the following options to complete. For either option, the choices of scheduler, framework, and storage are up to you.

### Option 1: Training

Demonstrate an end-to-end, multi-node training run of an open-source LLM. Run multiple experiments with various training distribution strategies to illustrate how the client may set up training on their cluster for a larger model (+100B). Document the training efficiency for each configuration.

### Option 2: Inference

Build a production-ready, end-to-end, reproducible multi-GPU inference server for an open-source LLM. Set up 2 different configurations where one optimizes for latency and the other optimizes for throughput. Server metrics should be emitted for simple observability.

Provide documentation so the client is able to recreate the setup in their own environment.

## PoC Capacity

The example should utilize the provided PoC capacity efficiently.

- 16 H200 GPU cards
- 2 TB SSD network disk
- 2 TB SSD shared filesystem



## Demo Day

During the demo day you will be asked to present your example to the customer and explain your technical choices. You should also provide necessary documentation (how to reproduce and monitor the example).

## Resources

- Solutions library: [https://github.com/nebius/nebius-solutions-library](https://github.com/nebius/nebius-solutions-library)
- K8s training: [https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training](https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training)
- Soperator (operator repo): [https://github.com/nebius/soperator](https://github.com/nebius/soperator)
- Soperator (deployment module): [https://github.com/nebius/nebius-solutions-library/tree/main/soperator](https://github.com/nebius/nebius-solutions-library/tree/main/soperator)
- Managed Soperator docs: [https://docs.nebius.com/slurm-soperator](https://docs.nebius.com/slurm-soperator)
- Nebius AI Cloud docs: [https://docs.nebius.com/](https://docs.nebius.com/)

