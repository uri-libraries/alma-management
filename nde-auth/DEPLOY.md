# Deploy to Linux Server

## 1. Install Go
```bash
wget https://go.dev/dl/go1.22.0.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go1.22.0.linux-amd64.tar.gz
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
source ~/.bashrc
```

## 2. Copy files
```bash
scp email-identifier.go go.mod go.sum .env user@yourserver:/path/to/dir/
```

## 3. Install dependencies
```bash
cd /path/to/dir
go mod tidy
```

## 4. Run
```bash
tmux new -s alma-update
go run email-identifier.go

# Detach: Ctrl+B then D
# Reattach: tmux attach -t alma-update
```

> Make sure `processed_users.log` does not exist before running in production:
> ```bash
> rm -f processed_users.log
> ```
