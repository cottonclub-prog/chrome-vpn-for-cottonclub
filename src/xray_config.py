"""Translate the supported VLESS profile to the official Xray client format."""


def make_xray_config(node, port, routing_mode='ru-direct'):
    from routing_policy import apply_xray
    out = node['outbound']
    if out['type'] != 'vless':
        raise ValueError('Xray adapter only accepts VLESS')
    user = {'id': out['uuid'], 'encryption': 'none'}
    if out.get('flow'):
        user['flow'] = out['flow']
    stream = {'network': 'raw', 'security': 'none'}
    tls = out.get('tls', {})
    if tls.get('enabled'):
        fingerprint = tls.get('utls', {}).get('fingerprint', 'chrome')
        if tls.get('reality', {}).get('enabled'):
            stream.update(security='reality', realitySettings={
                'serverName': tls['server_name'], 'fingerprint': fingerprint,
                'password': tls['reality']['public_key'],
                'shortId': tls['reality'].get('short_id', ''),
            })
        else:
            settings = {'serverName': tls['server_name'], 'fingerprint': fingerprint}
            if tls.get('alpn'):
                settings['alpn'] = tls['alpn']
            stream.update(security='tls', tlsSettings=settings)
    transport = out.get('transport', {})
    if transport.get('type') == 'ws':
        stream.update(network='ws', wsSettings={
            'path': transport.get('path', '/'), 'headers': transport.get('headers', {})})
    elif transport.get('type') == 'grpc':
        stream.update(network='grpc', grpcSettings={'serviceName': transport.get('service_name', '')})
    elif transport:
        raise ValueError('Unsupported Xray transport')
    config = {
        'log': {'loglevel': 'error'},
        'inbounds': [{'tag': 'browser', 'listen': '127.0.0.1', 'port': port,
                      'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': False}}],
        'outbounds': [{'tag': 'vpn', 'protocol': 'vless', 'settings': {
            'vnext': [{'address': out['server'], 'port': out['server_port'], 'users': [user]}]},
            'streamSettings': stream}],
    }
    return apply_xray(config, routing_mode)
