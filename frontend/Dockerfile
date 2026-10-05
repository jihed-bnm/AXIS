FROM nginx:alpine

# Copy only the files the browser needs — skip node_modules, package.json, logs
COPY static/axis.html          /usr/share/nginx/html/index.html
COPY static/css/               /usr/share/nginx/html/static/css/
COPY static/tour/              /usr/share/nginx/html/static/tour/

COPY frontend/nginx.conf       /etc/nginx/conf.d/default.conf

EXPOSE 80
