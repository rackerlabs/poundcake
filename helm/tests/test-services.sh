#!/bin/bash
set -ex

# Test that all required services are deployed
echo "Testing required services..."

# Check for API service
kubectl get svc poundcake-api -n poundcake || exit 1

# Check for StackStorm API service
kubectl get svc stackstorm-api -n poundcake || exit 1

# Check for StackStorm web service
kubectl get svc stackstorm-web -n poundcake || exit 1

# Check for database services
kubectl get svc poundcake-mariadb -n poundcake || exit 1
kubectl get svc stackstorm-mongodb -n poundcake || exit 1
kubectl get svc stackstorm-rabbitmq -n poundcake || exit 1
kubectl get svc stackstorm-redis -n poundcake || exit 1

# Check for required deployments
kubectl get deployment poundcake-api -n poundcake || exit 1
kubectl get deployment stackstorm-api -n poundcake || exit 1
kubectl get deployment stackstorm-web -n poundcake || exit 1

# Check for pod disruption budgets
kubectl get poddisruptionbudget poundcake-api -n poundcake || exit 1
kubectl get poddisruptionbudget stackstorm-api -n poundcake || exit 1

echo "All required services are deployed successfully!"
