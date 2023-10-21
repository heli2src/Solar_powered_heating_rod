'''
heating rod controlled by w5100s-evb-pico

 
                   
'''
import utime
import math
import micropython
from machine import Pin, PWM, SPI
import time
import network
from mqtt import MQTTClient

PIN_MOSI = 19
PIN_MISO = 16
PIN_SCK = 18
PIN_CS = 17
PIN_RESET = 20
PWM_HEAT = 15
LED_BUITLTIN = 25               # For RP2040-HAT


#mqtt config
mqtt_server = '192.168.178.28'
client_id = 'Heating_Rod'
topic_heating_online = b'HeatingRod/online'
topic_heating_power = b'HeatingRod/power'

#defines for enable heating:
min_power = -50
min_solar = 200
min_battery = 0
min_forcePower = 30


class subTopics:
    topic = {'Smartmeter/1-0:16.7.0': ["power", '*'],
             'sma/TIME': ["mytime",  None],
             'sma/P_AC': ["solar", None],
             'Battery/power': ["battery", None],
             'HeatingRod/forcePower': ["forcePower", None]
             }
    
    def __init__(self):
        for topic in self.topic:
            setattr(self, self.topic[topic][0], 0)
        
    def set_client(self, client):
        self.client = client
    
    def subscribe(self):
        for topic in self.topic:
            self.client.subscribe(topic)
            
    def sub_callback(self, topic, msg):        
        topic = topic.decode('utf-8')
        value = msg.decode('utf-8')
        if topic in self.topic:
            split = self.topic[topic][1]
            value = int(value) if split is None else int(value.split(split)[0])
            setattr(self, self.topic[topic][0], value)    


pwm = PWM(Pin(PWM_HEAT, mode=Pin.OUT)) # Attach PWM object on the LED pin
pwm.duty_u16 (0)
led = Pin(LED_BUITLTIN, Pin.OUT)

#W5x00 chip init
def w5x00_init():
    spi=SPI(0,2_000_000, mosi=Pin(PIN_MOSI),miso=Pin(PIN_MISO),sck=Pin(PIN_SCK))
    nic = network.WIZNET5K(spi,Pin(PIN_CS),Pin(PIN_RESET)) #spi,cs,reset pin
    nic.active(True)
    nic.ifconfig(('192.168.178.38','255.255.255.0','192.168.178.1','8.8.8.8'))
    while not nic.isconnected():
        time.sleep(1)
        print(nic.regs())
    print(nic.ifconfig())    

#MQTT connect
def mqtt_connect(sub_callback):
    client = MQTTClient(client_id, mqtt_server, keepalive=60)
    client.set_callback(sub_callback)
    client.connect()
    print('Connected to %s MQTT Broker'%(mqtt_server))
    return client

#reconnect & reset
def reconnect():
    print('Failed to connected to Broker. Reconnecting...')
    time.sleep(5)
    machine.reset()
    
def power2pwm(power): 
    pwm = float(power) /1000.0 * 65536.0
    pwm = 65530 if pwm > 65500 else pwm
    return int(pwm)

# Settings
#pwm_led.freq(1_000)     # = 1kHz


def main():
    w5x00_init()
    subtopics = subTopics()
    try: 
        client = mqtt_connect(subtopics.sub_callback)
    except OSError as e:
        reconnect()

    subtopics.set_client(client)
    
    received_time = 0
    heating_power = 0
    lasttime = 0

    while True:
        #for duty in range(0,100, 1):
        #    pwm_led.duty_u16(32768)
        #for duty in range(65_536,0, -10):
        #    sleep(0.001)
        #    pwm_led.duty_u16(duty)

        time.sleep(.2)

        subtopics.subscribe()
        client.publish(topic_heating_online, "online")
        client.publish(topic_heating_power, str(heating_power))
        
        if received_time < subtopics.mytime:
            led.toggle()
            received_time = subtopics.mytime
            lasttime = utime.time()
            if subtopics.forcePower > min_forcePower:
                heating_power = subtopics.forcePower                
            elif subtopics.power < min_power and subtopics.solar > min_solar and subtopics.battery < min_battery:
                heating_power = heating_power - subtopics.power + min_power
            else:
                heating_power = 0
            pwmvalue = power2pwm(heating_power)
            pwm.duty_u16(pwmvalue)
            print(f'power = {subtopics.power}, solar = {subtopics.solar}, battery = {subtopics.battery}')
            print(f'pwmvalue = {pwmvalue}, forcePower = {subtopics.forcePower}, heating = {heating_power}')
        elif (lasttime + 8) < utime.time():
            # zeit abfragen, wenn länger als 5s keine time gesetzt wird, dann heating_power = 0
            heating_power = 0
            pwm.duty_u16(heating_power)
            print(f' lastime={lasttime}, utime = {utime.time()}')
            print(f'no update from time  -> set heating = 0')
        
    client.disconnect()        


if __name__ == "__main__":
    main()        