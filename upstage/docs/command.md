Locally, compress and then copy media to the coolify server:

`tar -czf media.tgz -C upstage/media . `\
`scp media.tgz root@coolify.iskt.co.uk:/tmp/`

On the server, unpack 

This command gets the container name in variable C

`C=$(docker ps --filter name=<uuid> --format '{{.Names}}' | head -1)`\ 
`docker cp /tmp/media.tgz $C:/tmp/media.tgz`\                                                                                                                                                                                                      
`docker exec -u root $C sh -c 'tar -xzf /tmp/media.tgz -C /data/media && chown -R upstage:upstage /data/media && rm /tmp/media.tgz'` 