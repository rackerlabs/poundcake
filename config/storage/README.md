# Shared Storage

This directory contains optional cluster-scoped storage manifests and examples used by PoundCake.

## Longhorn RWX

Longhorn supports `ReadWriteMany` volumes through share-manager pods backed by NFSv4. For
StackStorm pack storage, use an RWX-capable StorageClass and make sure worker nodes have an NFSv4
client installed.

Included manifest:

- `longhorn-rwx-storageclass.yaml`: example StorageClass for shared StackStorm pack and virtualenv
  PVCs

You can apply it directly:

```bash
kubectl apply -f config/storage/longhorn-rwx-storageclass.yaml
```

Or let the Helm chart create the same class by enabling:

```yaml
longhorn:
  rwxStorageClass:
    create: true
    name: longhorn-rwx
```
