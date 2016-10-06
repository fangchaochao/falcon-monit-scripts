#!/bin/env python
#-*- coding:utf-8 -*-

__author__ = 'iambocai'

import json
import time
import socket
import os
import re
import sys
import commands
import urllib2, base64
import fcntl
import struct



def get_ip_address(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8915,  # SIOCGIFADDR
        struct.pack('256s', ifname[:15])
    )[20:24])



class RedisStats:
    # 如果你是自己编译部署到redis，请将下面的值替换为你到redis-cli路径
    _redis_cli = '/data/app/redis/bin/redis-cli'
    _stat_regex = re.compile(ur'(\w+):([0-9]+\.?[0-9]*)\r')
    _keys_regex = re.compile(r'keys=(\d{1,})')
    _expires_regex = re.compile(r'expires=(\d{1,})')


    def __init__(self,  port='6379', passwd=None, host='10.25.169.183'):

        self._cmd = '%s -h %s -p %s info' % (self._redis_cli, host, port)
        if passwd not in ['', None]:
            self._cmd = "%s -a %s" % (self._cmd, passwd )

        self._cmd_key = '%s -h %s -p %s info|grep :keys' % (self._redis_cli, host, port)
        if passwd not in ['', None]:
            self._cmd_key = "%s -a %s" % (self._cmd_key, passwd)


    def stats(self):
        ' Return a dict containing redis stats '
        info = commands.getoutput(self._cmd)
        return dict(self._stat_regex.findall(info))

    def get_keys(self):
        info = commands.getoutput(self._cmd_key)
        keyslist = self._keys_regex.findall(info)
        if keyslist:
            sum = reduce(lambda x, y: int(x) + int(y), keyslist)
        else:
            sum = 0
        return  sum

    def get_keys_expires(self):
        info = commands.getoutput(self._cmd_key)
        keyslist = self._expires_regex.findall(info)
        if keyslist:
            sum = reduce(lambda x, y: int(x) + int(y), keyslist)
        else:
            sum = 0
        return sum


def main():
    ip = socket.gethostname()
    timestamp = int(time.time())
    step = 60
    # inst_list中保存了redis配置文件列表，程序将从这些配置中读取port和password，建议使用动态发现的方法获得，如：
    insts_list = [ i for i in commands.getoutput("find  /data/app/redis -name 'redis*.conf'" ).split('\n') ]
    #insts_list = [ '/etc/redis.conf' ]
    p = []
    
    monit_keys = [
        ('connected_clients','GAUGE'), 
        ('blocked_clients','GAUGE'), 
        ('used_memory','GAUGE'),
        ('used_memory_rss','GAUGE'),
        ('mem_fragmentation_ratio','GAUGE'),
        ('total_commands_processed','COUNTER'),
        ('rejected_connections','COUNTER'),
        ('expired_keys','COUNTER'),
        ('evicted_keys','COUNTER'),
        ('keyspace_hits','COUNTER'),
        ('keyspace_misses','COUNTER'),
        ('keyspace_hit_ratio','GAUGE'),
        ('cpuuse_percent','GAUGE'),
        ('used_memory_percent', 'GAUGE'),
        ('instantaneous_input_kbps', 'GAUGE'),
        ('instantaneous_output_kbps', 'GAUGE'),
        ('total_keys', 'GAUGE'),
        ('total_keys_expires', 'GAUGE'),

    ]
  
    for inst in insts_list:
        port = commands.getoutput("sed -n 's/^port *\([0-9]\{4,5\}\)/\\1/p' %s" % inst)
        passwd = commands.getoutput("sed -n 's/^requirepass *\([^ ]*\)/\\1/p' %s" % inst)
        metric = "redis"
        endpoint = ip
        tags = 'port=%s' % port
        host = get_ip_address("eth0")
        try:
            conn = RedisStats(port, passwd,host)
            stats = conn.stats()
        except Exception,e:
            continue

        for key,vtype in monit_keys:
            if key == 'keyspace_hit_ratio':
                try:
                    value = float(stats['keyspace_hits'])/(int(stats['keyspace_hits']) + int(stats['keyspace_misses']))
                except ZeroDivisionError:
                    value = 0
            elif key == 'mem_fragmentation_ratio':
                value = float(stats[key])

            elif key == "cpuuse_percent":
                #获取rediscpu使用率
                cpuuse = commands.getoutput("ps aux|grep ':%s'|grep redis-server|awk '{print $3}'" % str(port))
                value = float(cpuuse.split('\n')[0])


            elif key == "used_memory_percent":
                value = float(stats['used_memory']) / float(stats['maxmemory']) * 100
            elif "instantaneous" in key:
                value = float(stats[key]) * 1024
            elif key == "total_keys":
                try:
                    conn = RedisStats(port, passwd, host)
                    value = conn.get_keys()
                except Exception, e:
                    continue

            elif key == "total_keys_expires":
                try:
                    conn = RedisStats(port, passwd, host)
                    value = conn.get_keys_expires()
                except Exception, e:
                    continue


            else:
                try:
                    value = int(stats[key])
                except:
                    continue
            
            i = {
                'Metric': '%s.%s' % (metric, key),
                'Endpoint': endpoint,
                'Timestamp': timestamp,
                'Step': step,
                'Value': value,
                'CounterType': vtype,
                'TAGS': tags
            }
            p.append(i)


    print json.dumps(p, sort_keys=True,indent=4)
    method = "POST"
    handler = urllib2.HTTPHandler()
    opener = urllib2.build_opener(handler)
    url = 'http://127.0.0.1:1988/v1/push'
    request = urllib2.Request(url, data=json.dumps(p) )
    request.add_header("Content-Type",'application/json')
    request.get_method = lambda: method
    try:
        connection = opener.open(request)
    except urllib2.HTTPError,e:
        connection = e

    # check. Substitute with appropriate HTTP code.
    if connection.code == 200:
        print connection.read()
    else:
        print '{"err":1,"msg":"%s"}' % connection
if __name__ == '__main__':
    proc = commands.getoutput(' ps -ef|grep %s|grep -v grep|wc -l ' % os.path.basename(sys.argv[0]))
    if int(proc) < 5:
        main()
