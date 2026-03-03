# Canales 1-5 en puerto 8080 apuntando a tu servidor RTSP
python onvif_server.py --port 8080 --channels 1-5 --rtsp-host 10.70.6.3 --rtsp-port 8555 --rtsp-path /sistema/video{i}

# Canales 6-10 en otro puerto
python onvif_server.py --port 8081 --channels 6-10 --rtsp-host 10.70.6.3 --rtsp-port 8555 --rtsp-path /cov/canal{i}
```

La salida va a mostrar correctamente el puerto y los paths:
```
  Camara 1     -> rtsp://10.70.6.3:8555/sistema/video1
  Camara 2     -> rtsp://10.70.6.3:8555/sistema/video2
  ...
