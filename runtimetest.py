#!/usr/bin/env python3
# runtimetest.py

from time import strftime, gmtime, sleep
import time
import math
import os.path
from os import path
import csv
import board
import busio
import adafruit_tsl2591
import RPi.GPIO as GPIO
import argparse
import sys

def init():
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = adafruit_tsl2591.TSL2591(i2c)
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)  
    ready_led = 17
    running_led = 27
    complete_led = 22
    GPIO.setup(ready_led, GPIO.OUT)
    GPIO.setup(running_led, GPIO.OUT)
    GPIO.setup(complete_led, GPIO.OUT)
    GPIO.output(ready_led, GPIO.HIGH)
    GPIO.output(running_led, GPIO.LOW)
    GPIO.output(complete_led, GPIO.LOW)
    return ready_led, running_led, complete_led

def write_to_csv(filename, t, lux):
    with open (filename, "a") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow([t, lux])

def blink_led(pin):
    GPIO.output(pin, not GPIO.input(pin))

def current_timestamp():
    return time.strftime("%H:%M:%S ", time.localtime())

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o','--outputfile', dest='filename', default=time.strftime('RuTiTe%Y-%m-%d-%H.%M.%S.csv', time.localtime()),help='filename for the csv output')
    parser.add_argument('-i','--interval', dest='delay', type=float, default=1.0, help='interval between measurements in seconds (halved during the 30s sampling period at the beginning of the test)')
    parser.add_argument('-d','--duration', type=float, help='maximum duration of the test in minutes')
    parser.add_argument('-tp','--termination-percentage', dest='termination_percentage', type=float, default=10.0, help='percent output to stop recording at')
    parser.add_argument('-pp','--print-percentage', dest='percent_change_to_print', type=float, default=5.0, help='percent change between printed updates to the terminal')
    parser.add_argument('-pd','--print-delay', dest='time_between_prints', type=float, help='minutes between printed updates to the terminal')
    return parser

def load_options():
    parser = build_parser()
    options = parser.parse_args()
    if options.time_between_prints:
        options.time_between_prints *= 60
    if os.path.isfile(options.filename):
        print ("{}{} already exists. Checking for an an available name to avoid overwriting something important...".format(current_timestamp(), options.filename))
        options.filename = time.strftime('RuTiTe%Y-%m-%d-%H.%M.%S.csv', time.localtime())
    print ("{}Saving as {}".format(current_timestamp(),options.filename))
    return options

def add_csv_header(filename):
    with open (filename, "a") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(["time", "lux"])
        blink_led(running_led)

def core(options):
    sensor_ceiling = 88000.0 
    state = 'set_baseline'
    baseline_sum = 0.0
    baseline_measurement_count = 0
    ceiling_reached = False
    
    while state != 'exit':
        lux = sensor.lux
        t = time.time()
        
        if lux == sensor_ceiling and ceiling_reached == False:
            print("{}Sensor is saturated. The light is too bright to measure with your current setup. Consider adding a filter between the source and the sensor. The test will continue, but will be cut off at the high end.".format(current_timestamp()))
            ceiling_reached = True
        
        if state == 'set_baseline':
            baseline_measurement_count += 1
            baseline_sum += lux
            
        if state == 'waiting_for_threshold':
            blink_led(ready_led)
            time.sleep(0.5)

        if state in ['sampling_period', 'main_recording']:
            write_to_csv(options.filename, t, lux)
            blink_led(running_led)
            
        if state == 'sampling_period':
            if lux < sampling_lux_min:
                sampling_lux_min = lux
            if lux > sampling_lux_max:
                sampling_lux_max = lux
            time.sleep(0.5)

        if state == 'main_recording':
            percent_output = lux / lux_at_30s * 100.0
            
            if options.time_between_prints and (t - last_print_time) > options.time_between_prints:
                print("{}Output is at {:.0f}% ({:.0f} lux)".format(current_timestamp(),percent_output, lux))
                last_print_time = t
                last_printed_percent = percent_output
            elif options.percent_change_to_print and abs(percent_output - last_printed_percent) >= options.percent_change_to_print:
                print("{}Output is at {:.0f}% ({:.0f} lux)".format(current_timestamp(),percent_output, lux))
                last_print_time = t
                last_printed_percent = percent_output
                
        if state in ['set_baseline', 'waiting_for_threshold', 'sampling_period'] and options.delay > 0.5:
            time.sleep(0.5)
        else:
            time.sleep(options.delay)
        
        if state == 'set_baseline' and baseline_measurement_count >= 5:
            threshold_lux = baseline_sum / baseline_measurement_count * 3.0
            state = 'waiting_for_threshold'
            print ("{}Ready to start the test. Turn on the light now.".format(current_timestamp()))
                
        if state == 'waiting_for_threshold' and lux >= threshold_lux:
            state = 'sampling_period'
            GPIO.output(ready_led, GPIO.HIGH)
            t_test_start = time.time()
            t_sampling_complete = t_test_start + 30.0
            t_test_complete = t_test_start + test_duration
            sampling_lux_min = sensor_ceiling
            sampling_lux_max = 0.0
            print ("{}Light detected. Recording started.".format(current_timestamp()))
            time.sleep(1.0)
        
        if state == 'sampling_period' and t >= t_sampling_complete:
            state = 'main_recording'
            lux_at_30s = lux                    
            print("{}Sampling period complete. The output at 30s was {:.1f} lux. Sampling period max = {:.1f} lux, min = {:.1f} lux.".format(current_timestamp(), lux_at_30s, sampling_lux_max, sampling_lux_min))
                text_to_print = '\tThe test will run until you stop it'
            if options.test_duration:
                text_to_print += ', or it has recorded for {:.0f} minutes'.format(options.test_duration/60)
            if options.termination_percentage:
                termination_output = lux_at_30s * options.termination_percentage / 100
                text_to_print += ', or it reaches {:.1f} lux ({}% of the output at 30s)'.format(termination_output, options.termination_percentage)
            print(text_to_print + '.')
            last_printed_percent = 100.0
            last_print_time = t
        
        if state == 'main_recording':
            if options.termination_percentage and percent_output <= termination_percentage:
                options.termination_percentage = False
                t_remaining = (t - t_test_start) * 0.05
                print("{}Output has reached {:.0f}% ({:.0f} lux), which is at or below your {}% target.".format(current_timestamp(), percent_output, lux, options.termination_percentage))
                last_print_time = t
                last_printed_percent = percent_output
                if options.test_duration and (t + t_remaining) > options.test_duration:
                    t_remaining = options.test_duration - t
                else:
                    t_test_complete = t + t_remaining
                    options.test_duration = t - t_remaining + t_remaining
                print("\tJust collecting a bit more data. The test will end in {:.1f} minutes.".format(t_remaining/60))
        
            if options.test_duration and t >= t_test_complete:
                state = 'exit'
                
    print("{}Test complete".format(current_timestamp()))
    GPIO.output(ready_led, GPIO.LOW)
    GPIO.output(running_led, GPIO.LOW)
    GPIO.output(complete_led, GPIO.HIGH)

def main():
    init()
    options = load_options()
    add_csv_header(options.filename)
    core(options)
    
if __name__ == "__main__":
    main()
