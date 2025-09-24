#!/bin/bash
docker-compose down 
sleep 1
docker-compose build --no-cache app worker
sleep 1
docker ps -a 
docker-compose up -d 
