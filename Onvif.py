"""
ONVIF Server en Python - Multi Canal - Produccion
==================================================
Dependencias:
    pip install flask lxml waitress

Uso:
    python onvif_server.py
    python onvif_server.py --port 8081 --channels 6-10
    python onvif_server.py --port 8082 --channels 1-5 --rtsp-host 10.70.6.3 --rtsp-port 8555
    python onvif_server.py --port 8080 --channels 1-5 --rtsp-path /sistema/video{i}
"""

import argparse
from flask import Flask, request, Response
from lxml import etree
import datetime

app = Flask(__name__)

# ─── Argumentos de linea de comandos ─────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="ONVIF Server Multi Canal")
    parser.add_argument("--port",      type=int, default=8080,
                        help="Puerto HTTP del servidor ONVIF (default: 8080)")
    parser.add_argument("--channels",  type=str, default="1-5",
                        help="Rango de canales, ej: 1-5 o 6-10 (default: 1-5)")
    parser.add_argument("--rtsp-host", type=str, default="127.0.0.1",
                        help="Host RTSP (default: 127.0.0.1)")
    parser.add_argument("--rtsp-port", type=int, default=8554,
                        help="Puerto RTSP (default: 8554)")
    parser.add_argument("--rtsp-path", type=str, default="/sistema/video{i}",
                        help="Path RTSP por canal, usa {i} como placeholder (default: /sistema/video{i})")
    parser.add_argument("--threads",   type=int, default=8,
                        help="Threads de Waitress (default: 8)")
    return parser.parse_args()


def parse_channel_range(channels_str):
    try:
        if "-" in channels_str:
            start, end = channels_str.split("-")
            return list(range(int(start), int(end) + 1))
        else:
            return [int(channels_str)]
    except ValueError:
        raise ValueError(f"Formato invalido: '{channels_str}'. Use ej: 1-5 o 6-10")


def build_channels(channel_ids, rtsp_host, rtsp_port, rtsp_path_template):
    return {
        f"Channel_{i}": {
            "profile_token": f"Profile_{i}",
            "source_token":  f"VideoSource_{i}",
            "encoder_token": f"VideoEncoder_{i}",
            "rtsp_uri":      f"rtsp://{rtsp_host}:{rtsp_port}{rtsp_path_template.format(i=i)}",
            "name":          f"Camara {i}",
            "width":         1920,
            "height":        1080,
            "framerate":     30,
            "bitrate":       4096,
        }
        for i in channel_ids
    }


# ─── Configuracion general ────────────────────────────────────────────────────

DEVICE_INFO = {
    "Manufacturer":    "MiEmpresa",
    "Model":           "CamaraVirtual-MultiCanal",
    "FirmwareVersion": "1.0.0",
    "SerialNumber":    "SN-20240001",
    "HardwareId":      "HW-v1",
}

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080   # se sobreescribe en main()
CHANNELS    = {}     # se llena en main()


# ─── Helpers de busqueda de canal ─────────────────────────────────────────────

def _channel_by_profile(token):
    for ch in CHANNELS.values():
        if ch["profile_token"] == token:
            return ch
    return list(CHANNELS.values())[0]

def _channel_by_source(token):
    for ch in CHANNELS.values():
        if ch["source_token"] == token:
            return ch
    return list(CHANNELS.values())[0]

def _channel_by_encoder(token):
    for ch in CHANNELS.values():
        if ch["encoder_token"] == token:
            return ch
    return list(CHANNELS.values())[0]


# ─── Helpers SOAP ─────────────────────────────────────────────────────────────

def soap_envelope(body_content):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope
    xmlns:s="http://www.w3.org/2003/05/soap-envelope"
    xmlns:tt="http://www.onvif.org/ver10/schema"
    xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
    xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <s:Body>
    {body_content}
  </s:Body>
</s:Envelope>"""

def soap_fault(code, reason):
    return soap_envelope(f"""<s:Fault>
      <s:Code><s:Value>{code}</s:Value></s:Code>
      <s:Reason><s:Text xml:lang="en">{reason}</s:Text></s:Reason>
    </s:Fault>""")

def parse_action(xml_bytes):
    try:
        root = etree.fromstring(xml_bytes)
        body = root.find("{http://www.w3.org/2003/05/soap-envelope}Body")
        if body is not None and len(body):
            tag = body[0].tag
            return tag.split("}")[-1] if "}" in tag else tag
    except Exception:
        pass
    return ""

def parse_token_from_body(xml_bytes, tag_name):
    try:
        root = etree.fromstring(xml_bytes)
        for elem in root.iter():
            local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local == tag_name and elem.text:
                return elem.text.strip()
    except Exception:
        pass
    return ""

def xml_response(content):
    return Response(content, mimetype="application/soap+xml; charset=utf-8")

def _server_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ─── Bloques XML por canal ────────────────────────────────────────────────────

def _encoder_xml(ch, tag="trt:Configurations"):
    return f"""<{tag} token="{ch['encoder_token']}">
        <tt:Name>{ch['name']} H264</tt:Name>
        <tt:UseCount>1</tt:UseCount>
        <tt:Encoding>H264</tt:Encoding>
        <tt:Resolution>
          <tt:Width>{ch['width']}</tt:Width><tt:Height>{ch['height']}</tt:Height>
        </tt:Resolution>
        <tt:Quality>5</tt:Quality>
        <tt:RateControl>
          <tt:FrameRateLimit>{ch['framerate']}</tt:FrameRateLimit>
          <tt:EncodingInterval>1</tt:EncodingInterval>
          <tt:BitrateLimit>{ch['bitrate']}</tt:BitrateLimit>
        </tt:RateControl>
        <tt:H264>
          <tt:GovLength>30</tt:GovLength>
          <tt:H264Profile>High</tt:H264Profile>
        </tt:H264>
        <tt:Multicast>
          <tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>
          <tt:Port>0</tt:Port><tt:TTL>0</tt:TTL><tt:AutoStart>false</tt:AutoStart>
        </tt:Multicast>
        <tt:SessionTimeout>PT60S</tt:SessionTimeout>
      </{tag}>"""

def _source_cfg_xml(ch, tag="trt:Configurations"):
    return f"""<{tag} token="{ch['source_token']}">
        <tt:Name>{ch['name']}</tt:Name>
        <tt:UseCount>1</tt:UseCount>
        <tt:SourceToken>{ch['source_token']}</tt:SourceToken>
        <tt:Bounds x="0" y="0" width="{ch['width']}" height="{ch['height']}"/>
      </{tag}>"""

def _profile_xml(ch, profile_tag="trt:Profiles"):
    return f"""<{profile_tag} token="{ch['profile_token']}" fixed="true">
        <tt:Name>{ch['name']}</tt:Name>
        <tt:VideoSourceConfiguration token="{ch['source_token']}">
          <tt:Name>{ch['name']}</tt:Name>
          <tt:UseCount>1</tt:UseCount>
          <tt:SourceToken>{ch['source_token']}</tt:SourceToken>
          <tt:Bounds x="0" y="0" width="{ch['width']}" height="{ch['height']}"/>
        </tt:VideoSourceConfiguration>
        <tt:VideoEncoderConfiguration token="{ch['encoder_token']}">
          <tt:Name>{ch['name']} H264</tt:Name>
          <tt:UseCount>1</tt:UseCount>
          <tt:Encoding>H264</tt:Encoding>
          <tt:Resolution>
            <tt:Width>{ch['width']}</tt:Width><tt:Height>{ch['height']}</tt:Height>
          </tt:Resolution>
          <tt:Quality>5</tt:Quality>
          <tt:RateControl>
            <tt:FrameRateLimit>{ch['framerate']}</tt:FrameRateLimit>
            <tt:EncodingInterval>1</tt:EncodingInterval>
            <tt:BitrateLimit>{ch['bitrate']}</tt:BitrateLimit>
          </tt:RateControl>
          <tt:H264>
            <tt:GovLength>30</tt:GovLength>
            <tt:H264Profile>High</tt:H264Profile>
          </tt:H264>
          <tt:Multicast>
            <tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>
            <tt:Port>0</tt:Port><tt:TTL>0</tt:TTL><tt:AutoStart>false</tt:AutoStart>
          </tt:Multicast>
          <tt:SessionTimeout>PT60S</tt:SessionTimeout>
        </tt:VideoEncoderConfiguration>
      </{profile_tag}>"""


# ─── Device Service handlers ──────────────────────────────────────────────────

def handle_GetDeviceInformation():
    info = DEVICE_INFO
    return soap_envelope(f"""<tds:GetDeviceInformationResponse>
      <tds:Manufacturer>{info['Manufacturer']}</tds:Manufacturer>
      <tds:Model>{info['Model']}</tds:Model>
      <tds:FirmwareVersion>{info['FirmwareVersion']}</tds:FirmwareVersion>
      <tds:SerialNumber>{info['SerialNumber']}</tds:SerialNumber>
      <tds:HardwareId>{info['HardwareId']}</tds:HardwareId>
    </tds:GetDeviceInformationResponse>""")

def handle_GetSystemDateAndTime():
    now = datetime.datetime.utcnow()
    return soap_envelope(f"""<tds:GetSystemDateAndTimeResponse>
      <tds:SystemDateAndTime>
        <tt:DateTimeType>NTP</tt:DateTimeType>
        <tt:DaylightSavings>false</tt:DaylightSavings>
        <tt:TimeZone><tt:TZ>UTC</tt:TZ></tt:TimeZone>
        <tt:UTCDateTime>
          <tt:Time>
            <tt:Hour>{now.hour}</tt:Hour>
            <tt:Minute>{now.minute}</tt:Minute>
            <tt:Second>{now.second}</tt:Second>
          </tt:Time>
          <tt:Date>
            <tt:Year>{now.year}</tt:Year>
            <tt:Month>{now.month}</tt:Month>
            <tt:Day>{now.day}</tt:Day>
          </tt:Date>
        </tt:UTCDateTime>
      </tds:SystemDateAndTime>
    </tds:GetSystemDateAndTimeResponse>""")

def handle_GetCapabilities():
    base = f"http://{_server_ip()}:{SERVER_PORT}"
    return soap_envelope(f"""<tds:GetCapabilitiesResponse>
      <tds:Capabilities>
        <tt:Device>
          <tt:XAddr>{base}/onvif/device_service</tt:XAddr>
          <tt:Network>
            <tt:IPFilter>false</tt:IPFilter><tt:ZeroConfiguration>false</tt:ZeroConfiguration>
            <tt:IPVersion6>false</tt:IPVersion6><tt:DynDNS>false</tt:DynDNS>
          </tt:Network>
          <tt:System>
            <tt:DiscoveryResolve>false</tt:DiscoveryResolve>
            <tt:DiscoveryBye>false</tt:DiscoveryBye>
            <tt:RemoteDiscovery>false</tt:RemoteDiscovery>
            <tt:SystemBackup>false</tt:SystemBackup>
            <tt:SystemLogging>false</tt:SystemLogging>
            <tt:FirmwareUpgrade>false</tt:FirmwareUpgrade>
          </tt:System>
          <tt:IO><tt:InputConnectors>0</tt:InputConnectors><tt:RelayOutputs>0</tt:RelayOutputs></tt:IO>
          <tt:Security>
            <tt:TLS1.1>false</tt:TLS1.1><tt:TLS1.2>false</tt:TLS1.2>
            <tt:OnboardKeyGeneration>false</tt:OnboardKeyGeneration>
            <tt:AccessPolicyConfig>false</tt:AccessPolicyConfig>
            <tt:X.509Token>false</tt:X.509Token><tt:SAMLToken>false</tt:SAMLToken>
            <tt:KerberosToken>false</tt:KerberosToken><tt:RELToken>false</tt:RELToken>
          </tt:Security>
        </tt:Device>
        <tt:Media>
          <tt:XAddr>{base}/onvif/media_service</tt:XAddr>
          <tt:StreamingCapabilities>
            <tt:RTPMulticast>false</tt:RTPMulticast>
            <tt:RTP_TCP>true</tt:RTP_TCP>
            <tt:RTP_RTSP_TCP>true</tt:RTP_RTSP_TCP>
          </tt:StreamingCapabilities>
        </tt:Media>
      </tds:Capabilities>
    </tds:GetCapabilitiesResponse>""")

def handle_GetServices():
    base = f"http://{_server_ip()}:{SERVER_PORT}"
    return soap_envelope(f"""<tds:GetServicesResponse>
      <tds:Service>
        <tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace>
        <tds:XAddr>{base}/onvif/device_service</tds:XAddr>
        <tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version>
      </tds:Service>
      <tds:Service>
        <tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace>
        <tds:XAddr>{base}/onvif/media_service</tds:XAddr>
        <tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version>
      </tds:Service>
    </tds:GetServicesResponse>""")

def handle_GetScopes():
    return soap_envelope("""<tds:GetScopesResponse>
      <tds:Scopes>
        <tt:ScopeDef>Fixed</tt:ScopeDef>
        <tt:ScopeItem>onvif://www.onvif.org/type/video_encoder</tt:ScopeItem>
      </tds:Scopes>
      <tds:Scopes>
        <tt:ScopeDef>Fixed</tt:ScopeDef>
        <tt:ScopeItem>onvif://www.onvif.org/Profile/Streaming</tt:ScopeItem>
      </tds:Scopes>
    </tds:GetScopesResponse>""")

DEVICE_HANDLERS = {
    "GetDeviceInformation": handle_GetDeviceInformation,
    "GetSystemDateAndTime": handle_GetSystemDateAndTime,
    "GetCapabilities":      handle_GetCapabilities,
    "GetServices":          handle_GetServices,
    "GetScopes":            handle_GetScopes,
}

@app.route("/onvif/device_service", methods=["GET", "POST"])
def device_service():
    if request.method == "GET":
        return Response("ONVIF Device Service activo", mimetype="text/plain")
    action = parse_action(request.data)
    handler = DEVICE_HANDLERS.get(action)
    if handler:
        return xml_response(handler())
    return xml_response(soap_fault("s:Sender", f"Accion no soportada: {action}")), 400


# ─── Media Service handlers ───────────────────────────────────────────────────

def handle_GetProfiles():
    profiles = "".join(_profile_xml(ch, "trt:Profiles") for ch in CHANNELS.values())
    return soap_envelope(f"<trt:GetProfilesResponse>{profiles}</trt:GetProfilesResponse>")

def handle_GetProfile():
    token = parse_token_from_body(request.data, "ProfileToken")
    ch = _channel_by_profile(token)
    return soap_envelope(f"<trt:GetProfileResponse>{_profile_xml(ch, 'trt:Profile')}</trt:GetProfileResponse>")

def handle_GetStreamUri():
    token = parse_token_from_body(request.data, "ProfileToken")
    ch = _channel_by_profile(token)
    return soap_envelope(f"""<trt:GetStreamUriResponse>
      <trt:MediaUri>
        <tt:Uri>{ch['rtsp_uri']}</tt:Uri>
        <tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>
        <tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>
        <tt:Timeout>PT0S</tt:Timeout>
      </trt:MediaUri>
    </trt:GetStreamUriResponse>""")

def handle_GetSnapshotUri():
    base = f"http://{_server_ip()}:{SERVER_PORT}"
    token = parse_token_from_body(request.data, "ProfileToken")
    ch = _channel_by_profile(token)
    channel_id = ch["profile_token"].replace("Profile_", "")
    return soap_envelope(f"""<trt:GetSnapshotUriResponse>
      <trt:MediaUri>
        <tt:Uri>{base}/snapshot?channel={channel_id}</tt:Uri>
        <tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>
        <tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>
        <tt:Timeout>PT0S</tt:Timeout>
      </trt:MediaUri>
    </trt:GetSnapshotUriResponse>""")

def handle_GetVideoSources():
    sources = "".join(f"""<trt:VideoSources token="{ch['source_token']}">
        <tt:Framerate>{ch['framerate']}</tt:Framerate>
        <tt:Resolution>
          <tt:Width>{ch['width']}</tt:Width><tt:Height>{ch['height']}</tt:Height>
        </tt:Resolution>
      </trt:VideoSources>""" for ch in CHANNELS.values())
    return soap_envelope(f"<trt:GetVideoSourcesResponse>{sources}</trt:GetVideoSourcesResponse>")

def handle_GetVideoSourceConfigurations():
    configs = "".join(_source_cfg_xml(ch, "trt:Configurations") for ch in CHANNELS.values())
    return soap_envelope(f"<trt:GetVideoSourceConfigurationsResponse>{configs}</trt:GetVideoSourceConfigurationsResponse>")

def handle_GetVideoSourceConfiguration():
    token = parse_token_from_body(request.data, "ConfigurationToken")
    ch = _channel_by_source(token)
    return soap_envelope(f"<trt:GetVideoSourceConfigurationResponse>{_source_cfg_xml(ch, 'trt:Configuration')}</trt:GetVideoSourceConfigurationResponse>")

def handle_GetVideoEncoderConfigurations():
    configs = "".join(_encoder_xml(ch, "trt:Configurations") for ch in CHANNELS.values())
    return soap_envelope(f"<trt:GetVideoEncoderConfigurationsResponse>{configs}</trt:GetVideoEncoderConfigurationsResponse>")

def handle_GetVideoEncoderConfiguration():
    token = parse_token_from_body(request.data, "ConfigurationToken")
    ch = _channel_by_encoder(token)
    return soap_envelope(f"<trt:GetVideoEncoderConfigurationResponse>{_encoder_xml(ch, 'trt:Configuration')}</trt:GetVideoEncoderConfigurationResponse>")

def handle_GetCompatibleVideoEncoderConfigurations():
    token = parse_token_from_body(request.data, "ProfileToken")
    ch = _channel_by_profile(token)
    return soap_envelope(f"<trt:GetCompatibleVideoEncoderConfigurationsResponse>{_encoder_xml(ch, 'trt:Configurations')}</trt:GetCompatibleVideoEncoderConfigurationsResponse>")

def handle_GetCompatibleVideoSourceConfigurations():
    token = parse_token_from_body(request.data, "ProfileToken")
    ch = _channel_by_profile(token)
    return soap_envelope(f"<trt:GetCompatibleVideoSourceConfigurationsResponse>{_source_cfg_xml(ch, 'trt:Configurations')}</trt:GetCompatibleVideoSourceConfigurationsResponse>")

def handle_GetVideoEncoderConfigurationOptions():
    return soap_envelope("""<trt:GetVideoEncoderConfigurationOptionsResponse>
      <trt:Options>
        <tt:QualityRange><tt:Min>1</tt:Min><tt:Max>10</tt:Max></tt:QualityRange>
        <tt:H264>
          <tt:ResolutionsAvailable><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:ResolutionsAvailable>
          <tt:ResolutionsAvailable><tt:Width>1280</tt:Width><tt:Height>720</tt:Height></tt:ResolutionsAvailable>
          <tt:GovLengthRange><tt:Min>1</tt:Min><tt:Max>60</tt:Max></tt:GovLengthRange>
          <tt:FrameRateRange><tt:Min>1</tt:Min><tt:Max>30</tt:Max></tt:FrameRateRange>
          <tt:EncodingIntervalRange><tt:Min>1</tt:Min><tt:Max>1</tt:Max></tt:EncodingIntervalRange>
          <tt:H264ProfilesSupported>High</tt:H264ProfilesSupported>
        </tt:H264>
      </trt:Options>
    </trt:GetVideoEncoderConfigurationOptionsResponse>""")

MEDIA_HANDLERS = {
    "GetProfiles":                             handle_GetProfiles,
    "GetProfile":                              handle_GetProfile,
    "GetStreamUri":                            handle_GetStreamUri,
    "GetSnapshotUri":                          handle_GetSnapshotUri,
    "GetVideoSources":                         handle_GetVideoSources,
    "GetVideoSourceConfigurations":            handle_GetVideoSourceConfigurations,
    "GetVideoSourceConfiguration":             handle_GetVideoSourceConfiguration,
    "GetCompatibleVideoSourceConfigurations":  handle_GetCompatibleVideoSourceConfigurations,
    "GetVideoEncoderConfigurations":           handle_GetVideoEncoderConfigurations,
    "GetVideoEncoderConfiguration":            handle_GetVideoEncoderConfiguration,
    "GetCompatibleVideoEncoderConfigurations": handle_GetCompatibleVideoEncoderConfigurations,
    "GetVideoEncoderConfigurationOptions":     handle_GetVideoEncoderConfigurationOptions,
}

@app.route("/onvif/media_service", methods=["GET", "POST"])
def media_service():
    if request.method == "GET":
        return Response("ONVIF Media Service activo", mimetype="text/plain")
    action = parse_action(request.data)
    handler = MEDIA_HANDLERS.get(action)
    if handler:
        return xml_response(handler())
    return xml_response(soap_fault("s:Sender", f"Accion no soportada: {action}")), 400


# ─── Snapshot placeholder ─────────────────────────────────────────────────────

@app.route("/snapshot")
def snapshot():
    import base64
    pixel = base64.b64decode(
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
        "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
        "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAA"
        "AAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/"
        "aAAwDAQACEQMRAD8AJQAB/9k="
    )
    return Response(pixel, mimetype="image/jpeg")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from waitress import serve

    args = parse_args()

    # Sobreescribir variables globales con los argumentos
    SERVER_PORT = args.port
    channel_ids = parse_channel_range(args.channels)
    CHANNELS    = build_channels(channel_ids, args.rtsp_host, args.rtsp_port, args.rtsp_path)

    ip = _server_ip()
    print("=" * 60)
    print("  ONVIF Server Python - Produccion (Waitress)")
    print(f"  Canales        : {len(CHANNELS)}  ({args.channels})")
    print(f"  Threads        : {args.threads}")
    print("=" * 60)
    print(f"  Device Service : http://{ip}:{SERVER_PORT}/onvif/device_service")
    print(f"  Media  Service : http://{ip}:{SERVER_PORT}/onvif/media_service")
    print("-" * 60)
    for ch in CHANNELS.values():
        print(f"  {ch['name']:12s} -> {ch['rtsp_uri']}")
    print("=" * 60)

    serve(app, host=SERVER_HOST, port=SERVER_PORT, threads=args.threads)