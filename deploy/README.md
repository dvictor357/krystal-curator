# Deploy (one box, docker compose, nginx + certbot on the host)

```sh
git clone https://github.com/dvictor357/krystal-curator.git ~/curator && cd ~/curator
cp deploy/.env.example deploy/.env   # fill CURATOR_DB_PASSWORD, CURATOR_API_SECRET, CURATOR_ORIGIN
docker compose -f deploy/compose.yml --env-file deploy/.env up -d --build
sudo cp deploy/nginx.conf /etc/nginx/sites-available/curator.conf
sudo ln -sf /etc/nginx/sites-available/curator.conf /etc/nginx/sites-enabled/curator.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d 187-77-128-156.sslip.io
```

- The API is never published; only `web` (loopback :3200) is, and nginx fronts it.
- Migrations run on API start (`aerich upgrade`).
- Update: `git pull && docker compose -f deploy/compose.yml --env-file deploy/.env up -d --build`.
- Logs: `docker compose -f deploy/compose.yml logs -f api web`.
- With a real domain: change `server_name`, `CURATOR_ORIGIN`, rebuild `web` (origin is baked into the build), re-run certbot.
