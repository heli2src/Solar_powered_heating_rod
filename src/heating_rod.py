'''
Released under the MIT License (MIT). See LICENSE.

heating rod controlled by w5100s-evb-pico

 
                   
'''
import utime
import math
import micropython
from machine import Pin, PWM, SPI
import time
import network
from mqtt import MQTTClient

PIN_MOSI = 19                  # Pin 25   used for the internal SPI to LAN
PIN_MISO = 16                  # Pin 21   "
PIN_SCK = 18                   # Pin 24   "
PIN_CS = 17                    # Pin 22   "
PIN_RESET = 20                 # Pin 26   "

PWM_HEAT = 15                   # GP15 (Pin 20)  Channel 1 with PWM
CHANNEL_2 = 14                  # GP14 (Pin 19)  Channel 2
CHANNEL_3 = 13                  # GP13 (Pin 17)  Channel 3
LED_BUITLTIN = 25               # For RP2040-HAT

debug = False

#mqtt config
mqtt_server = '102.130.150.280'
client_id = 'Heating_Rod'
topic_heating_online = b'HeatingRod/online'
topic_heatingPower = b'HeatingRod/power'

#defines for enable heating:
min_power = 80
min_solar = 200
min_battery = 0
reduced_batteryload = 650
max_batteryload = 1800
min_forcePower = 30

power2pwmList = [
    (960, 65500),
    (950, 59800),
    (900, 49900),    
    (850, 46600),
    (800, 44100),
    (750, 42200),
    (700, 40000),
    (650, 38600),
    (600, 37100),
    (550, 35800),
    (500, 34500),
    (450, 33200),
    (400, 32000),
    (350, 30900),
    (300, 29800),
    (250, 28700),
    (200, 27700),
    (150, 26500),
    (100, 25200),
    (80, 24700),
    (70, 0)
    ]

class subTopics:
    topic = {'Smartmeter/1-0:16.7.0': ["power", '*'],			# is negativ if supply the line
             'sma/TIME': ["smaTime",  None],
             'sma/P_AC': ["solar", None],
             'Battery/power': ["battery", None],
             'Battery/bat_state': ["bat_state", None],
             'HeatingRod/forcePower': ["forcePower", None],
             'HeatingRod/forcePWM': ["forcePWM", None]            
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
    for compare in power2pwmList:
        if power >= compare[0]:
            #print(f'        power2pwm: {power}, {compare}')
            return compare
    else:
        #print(f'        power2pwm: 0, {compare[1]}')
        return 0, compare[1]


def main():
    ch2 = Pin(CHANNEL_2, Pin.OUT)
    ch3 = Pin(CHANNEL_3, Pin.OUT)
    ch2.off()
    ch3.off()
    pwm = PWM(Pin(PWM_HEAT, mode=Pin.OUT)) # Attach PWM object on the LED pin
    pwm.duty_u16(power2pwm(0)[1])
    heatingPower = 0
    led = Pin(LED_BUITLTIN, Pin.OUT)
    w5x00_init()
    subtopics = subTopics()
    try: 
        client = mqtt_connect(subtopics.sub_callback)
    except OSError as e:
        reconnect()

    subtopics.set_client(client)
    
    received_time = 0
    heatingPower = 0
    lasttime = 0
    lastmqttTime = 0
    lastpower = 0
    lastcalculation = 0

    while True:
        time.sleep(.5)
        
        if subtopics.power != lastpower:
            led.toggle()
            received_time = subtopics.smaTime
            lasttime = utime.time()
            setPower = True
            if subtopics.forcePower > min_forcePower:
                heatingPower = subtopics.forcePower
            elif subtopics.forcePWM > 0:
                print(f'     forcePWM = {subtopics.forcePWM}')
                pwmvalue = subtopics.forcePWM
                heatingPower = -1
                setPower = False
            elif subtopics.solar > min_solar:
                batteryOffset = 0
                if (subtopics.bat_state == 0):
                    batteryOffset = 0
                elif (subtopics.bat_state == 1):
                    # battery is full or loading is disabled
                    batteryOffset = subtopics.battery
                elif subtopics.bat_state == 2:
                    # battery is loading with reduced power
                    batterOffset = reduced_batteryload
                elif  subtopics.bat_state == 3:
                    # battery is loading with max power
                    batteryOffset =  max_batteryload
                if lastcalculation == 0 or lasttime - lastcalculation > 4:
                    oldvalue = heatingPower
                    heatingPower = heatingPower - subtopics.power - min_power -batteryOffset
                    lastcalculation = lasttime
                    if debug:
                        print(f'     calculated new heatingPower = {heatingPower} = {oldvalue} - {subtopics.power} - {min_power} - {batteryOffset}, bat_status = {subtopics.bat_state}')
            else:
                if debug:
                    print(f'    bedingungen nicht erfuellt -> set heading = 0, solar={subtopics.solar}, power= {subtopics.power}')
                heatingPower = 0
            if setPower:
                heatingPower, pwmvalue = power2pwm(heatingPower)
            pwm.duty_u16(pwmvalue)
            
        elif received_time < subtopics.smaTime:
            received_time = subtopics.smaTime
            lasttime = utime.time()

        if (lastmqttTime + 1) <= utime.time():
            lastmqttTime = utime.time()
            subtopics.subscribe()
            client.publish(topic_heating_online, "online")
            client.publish(topic_heatingPower, str(heatingPower))
            if debug:
                print(f'power = {subtopics.power}, solar = {subtopics.solar}, battery = {subtopics.battery}, received_time = {received_time}   --> heating = {heatingPower}')
        if (lasttime + 6) < utime.time():   # something is wrong, more than 6s no change from received time -switch off
            lasttime = utime.time()
            heatingPower, pwmvalue = power2pwm(0)
            pwm.duty_u16(pwmvalue)
            print(f' lastime={lasttime}, utime = {utime.time()}')
            print(f'no update from time  -> set heating = 0')
        
    client.disconnect()        


if __name__ == "__main__":
    main()        