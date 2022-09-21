#! /bin/sh

# Provisioning in the debug mode on ARM64 server


wget https://storage.googleapis.com/minikube/releases/latest/minikube-linux-arm64
sudo install minikube-linux-arm64 /usr/local/bin/minikube

wget https://storage.googleapis.com/kubernetes-release/release/v1.25.1/bin/linux/arm64/kubectl
chmod +x kubectl
sudo mv kubectl /usr/local/bin/kubectl

wget https://get.helm.sh/helm-v3.9.4-linux-arm64.tar.gz
tar -zxvf helm-*.tar.gz
sudo mv linux-arm64/helm /usr/local/bin/helm

sh k8s/debug/provision.sh
