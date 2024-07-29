import network
import socket
from time import sleep
import machine
from machine import Pin, SPI, I2C
from sys import exit
from mcp3008 import MCP3008
import bme280
import _thread
import time

# WiFi credentials
ssid = 'WIFI_NAME' 
password = 'WIFI_PASSWORD' 

# Initialize I2C for BME280 and MCP3008
i2c = I2C(1, sda=Pin(14), scl=Pin(15), freq=100000)
spi = SPI(1, sck=Pin(10), mosi=Pin(11), miso=Pin(12), baudrate=100000)
cs = Pin(13, Pin.OUT)
cs.value(1) 
chip = MCP3008(spi, cs)

Vref = 3.3
bit = 10

# Global variables for rainfall and rain gauge
rainCount = 0
accumulatedRainfall = 0.0  

# Semaphore for thread safety
spLock = _thread.allocate_lock()

# Rain gauge setup on GPIO pin 1
def core1_task():
    global rainCount, spLock 

    # Rain Gauge
    rainInput = Pin(1, Pin.IN, Pin.PULL_UP)
    rainFlag = 0

    while True:
        if rainInput.value() == 0 and rainFlag == 1:
            spLock.acquire()  
            rainCount += 1  
            spLock.release()  

        rainFlag = rainInput.value() 
        sleep(0.01)  

_thread.start_new_thread(core1_task, ())

def connect():
    # Connect to WLAN
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    
    max_attempts = 10
    attempt = 0
    while not wlan.isconnected() and attempt < max_attempts:
        print('Waiting for connection...')
        sleep(1)
        attempt += 1
        
    if not wlan.isconnected():
        raise RuntimeError('Failed to connect to WLAN')
    
    ip = wlan.ifconfig()[0]
    print(f'Connect successful: IPv4 address: {ip}')
    return ip

def open_socket(ip):
    # Open a socket
    address = (ip, 80)
    connection = socket.socket()
    connection.bind(address)
    connection.listen(1)
    print('Socket listening on:', address)
    return connection

def webpage(temperature, humidity, pressure, rainfall):
    # Template HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Weather Station</title>
    <meta http-equiv="refresh" content="4">
    <link rel="stylesheet" href="https://use.fontawesome.com/releases/v5.7.2/css/all.css" integrity="sha384-fnmOCqbTlWIlj8LyTjo7mOUStjsKC4pOpQbqyi7RrhN7udi9RwhKkMHpvLbHG9Sr" crossorigin="anonymous">
    <style>
        body {{
            background-image: url('https://images.unsplash.com/photo-1506748686214-e9df14d4d9d0');
            background-size: cover;
            color: white;
            text-align: center;
            font-family: 'Arial', sans-serif;
            height: 100vh;
            margin: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}
        h1 {{
            font-size: 48px;
            border: 2px solid white;
            padding: 20px;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        .container {{
            display: grid;
            grid-template-rows: auto auto;
            gap: 20px;
            border: 2px solid white;
            padding: 15px;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 10px;
            max-width: 800px;
            margin: auto;
        }}
        .row {{
            display: flex;
            justify-content: space-around;
            gap: 20px;
            padding: 10px;
        }}
        .box {{
            border: 2px solid white;
            padding: 20px; /* Increased padding */
            background: rgba(0, 0, 0, 0.5);
            border-radius: 10px;
            flex: 1;
            min-width: 200px; /* Ensure all boxes have minimum width */
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .box h2 {{
            font-size: 24px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
        }}
        .box h2 img {{
            width: 30px; /* Adjust icon size as needed */
            margin-right: 10px; /* Spacing between icon and text */
        }}
        .box p {{
            font-size: 20px;
            margin: 0;
        }}
    </style>
    </head>
    <body>
        <h1>WEATHER STATION</h1>
        <div class="container">
            <div class="row">
                <div class="box">
                    <h2><i class="fas fa-thermometer-half"></i> Temperature</h2>
                    <p>{temperature:.2f} &deg;C</p>
                </div>
                <div class="box">
                    <h2><i class="fas fa-tint"></i> Humidity</h2>
                    <p>{humidity:.2f} %</p>
                </div>
            </div>
            <div class="row">
                <div class="box">
                    <h2><i class="fas fa-tachometer-alt"></i> Pressure</h2>
                    <p>{pressure} </p>
                </div>
                <div class="box">
                    <h2><i class="fas fa-cloud-rain"></i> Rainfall</h2>
                    <p>{rainfall:.2f} mm</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return str(html)

def log_to_csv(temperature, humidity, pressure, rainfall):
    try:
        t = time.localtime()
        current_time = time.strftime("%Y/%m/%d %H:%M:%S", t)
        data_entry = f"{current_time}, {temperature:.2f}, {humidity:.2f}, {pressure:.2f}, {rainfall:.2f}\n"
        
        with open("/WEATHER.csv", "a") as f:
            f.write(data_entry)
            
        print(f"Logged data: {data_entry.strip()}")
    except Exception as e:
        print(f"Error writing to CSV file: {e}")

def serve(connection):
    global rainCount, accumulatedRainfall, spLock  

    # Ensure CSV file has header
    try:
        with open("/WEATHER.csv", "r") as f:
            pass
    except OSError:
        with open("/WEATHER.csv", "w") as f:
            f.write("Date and Time, Temperature (BME280), Humidity (BME280), Pressure (BME280), Rainfall\n")

    while True:
        client = None
        try:
            client, addr = connection.accept()
            request = client.recv(1024)
            
            # Read sensor data
            T_vol = (chip.read(1) * Vref / (2**bit) - 0.5) * 100
            RH_vol = chip.read(0) * Vref / (2**bit) * 100
            bme = bme280.BME280(i2c=i2c)
            temperature = T_vol
            humidity = RH_vol
            pressure = bme.values[1]
            
            # Calculate Rainfall
            spLock.acquire() 
            accumulatedRainfall += rainCount * 0.5  
            rainCount = 0 
            spLock.release() 

            # Log data to CSV
            log_to_csv(temperature, humidity, pressure, accumulatedRainfall)

            # Prepare and send response with updated sensor values
            html = webpage(temperature, humidity, pressure, accumulatedRainfall)
            response = 'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n' + html
            client.sendall(response.encode('utf-8'))
            client.close()
            
            sleep(4) 
            
        except OSError as err:
            print(f'Error: {err}')
            if client:
                client.close()
            print('Connection closed due to error')

try:
    ip = connect()
    connection = open_socket(ip)
    serve(connection)
except KeyboardInterrupt:
    print("Server stopped by user")
    machine.reset()
except Exception as e:
    print(f"Unexpected error: {e}")
    machine.reset()
