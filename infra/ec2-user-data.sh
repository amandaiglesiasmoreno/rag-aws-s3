#!/bin/bash
# EC2 "User data" for Amazon Linux 2023: installs Docker and git on first boot.
dnf update -y
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user
