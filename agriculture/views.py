import requests
from PIL import Image
import numpy as np
from io import BytesIO
from django.shortcuts import render, redirect
import random
import os

def home(request):
    return render(request, 'home.html')  # Render the home page

def home_to_loading(request):
    gps_coordinates = request.GET.get("gps_coordinates")
    radius = request.GET.get("radius")
    return render(request, 'loading_to_results.html', {
        "gps_coordinates": gps_coordinates,
        "radius": radius,
    })

def prediction_model(request):
    # Fetch parameters from request
    humidity = int(request.GET.get("humidity", 0))
    temperature = float(request.GET.get("temperature", 0))
    soil_moisture = int(request.GET.get("soil_moisture", 0))
    crop_health = request.GET.get("crop_health", "Good")

    # Initialize prediction and confidence
    prediction = "No Outbreak Likely"
    confidence = random.uniform(90, 99)  # Default high confidence for safe conditions

    # Prediction logic with adjusted thresholds
    if (
        humidity > 90 and
        temperature > 35 and
        soil_moisture < 20 and
        crop_health == "Poor"
    ):
        prediction = "Extensive Outbreak"
        confidence = random.uniform(85, 95)
    elif (
        (80 < humidity <= 90) or
        (30 < temperature <= 35) or
        (20 <= soil_moisture < 30) or
        crop_health == "Average"
    ):
        prediction = "Possible Outbreak"
        confidence = random.uniform(75, 90)
    elif (
        (65 < humidity <= 80) or
        (25 < temperature <= 30) or
        (30 <= soil_moisture <= 50)
    ):
        prediction = "No Outbreak Possible"
        confidence = random.uniform(80, 95)

    return render(request, 'prediction.html', {
        "prediction": prediction,
        "confidence": round(confidence, 2),  # Confidence rounded to 2 decimal places
    })


def analyze_crop_health(image_url, radius):
    """
    Analyze crop health using a proxy NDVI calculation based on RGB values.
    """
    try:
        # Fetch the satellite image
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()

        # Save the image locally for processing
        temp_image_path = "temp_satellite_image.png"
        with open(temp_image_path, "wb") as f:
            f.write(response.content)

        # Open the saved image
        img = Image.open(temp_image_path)
        print(f"Image format: {img.format}, Size: {img.size}, Mode: {img.mode}")  # Debug image properties

        # Convert image to RGB if it's not already in RGB mode
        if img.mode != "RGB":
            print("Converting image to RGB mode for processing.")
            img = img.convert("RGB")

        # Convert image to numpy array for processing
        img_array = np.array(img)

        # Extract red and green channels
        red = img_array[:, :, 0].astype(float)
        green = img_array[:, :, 1].astype(float)

        # Calculate NDVI proxy
        ndvi = (green - red) / (green + red + 1e-5)  # Adding a small value to avoid division by zero
        mean_ndvi = ndvi.mean()
        print(f"Mean NDVI: {mean_ndvi:.2f}")  # Debug NDVI value

        # Map NDVI to crop health categories
        if mean_ndvi > 0.1:  # Adjusted threshold for "Good"
            crop_health = "Good"
        elif 0.05 <= mean_ndvi <= 0.1:  # Adjusted threshold for "Average"
            crop_health = "Average"
        else:  # NDVI < 0.05 for "Poor"
            crop_health = "Poor"

        return crop_health
    except Exception as e:
        print(f"Error analyzing crop health: {e}")
        return "Unknown"

def result(request):
    gps_coordinates = request.GET.get("gps_coordinates")
    radius = request.GET.get("radius")

    # Validate inputs
    if not gps_coordinates or not radius:
        return redirect("/")

    # Parse latitude and longitude
    try:
        latitude, longitude = map(float, gps_coordinates.split(","))
    except ValueError:
        return redirect("/")

    # Generate the Esri Satellite image URL
    satellite_image_url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox={longitude-0.01},{latitude-0.01},{longitude+0.01},{latitude+0.01}&bboxSR=4326&size=400,400&imageSR=4326&format=png&f=image"

    # Analyze crop health
    crop_health = analyze_crop_health(satellite_image_url, radius)

    # Fetch 7-day weather data
    weather_api_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto"
    current_weather = {}
    try:
        response = requests.get(weather_api_url)
        if response.status_code == 200:
            data = response.json().get("daily", {})
            dates = data.get("time", [])
            max_temps = data.get("temperature_2m_max", [])
            if dates and max_temps:
                current_weather = {
                    "date": dates[0],
                    "max_temp": max_temps[0]
                }
    except Exception as e:
        print(f"Error fetching weather data: {e}")

    # Simulate additional environmental stats
    humidity = np.random.randint(50, 100)
    soil_moisture = np.random.randint(20, 90)
    wind_speed = np.random.uniform(5, 20)
    fertilizer_usage = np.random.choice(["Low", "Moderate", "High"])

    # Pass results to the template
    return render(request, "result.html", {
        "gps_coordinates": gps_coordinates,
        "radius": radius,
        "crop_health": crop_health,
        "humidity": humidity,
        "soil_moisture": soil_moisture,
        "wind_speed": round(wind_speed, 2),
        "fertilizer_usage": fertilizer_usage,
        "satellite_image_url": satellite_image_url,
        "current_weather": current_weather
    })

def results_to_loading(request):
    gps_coordinates = request.GET.get("gps_coordinates")
    humidity = request.GET.get("humidity")
    temperature = request.GET.get("temperature")
    soil_moisture = request.GET.get("soil_moisture")
    crop_health = request.GET.get("crop_health")

    # Validate the inputs
    try:
        if not temperature or temperature == '':
            raise ValueError("Temperature value is missing.")
        temperature = float(temperature)
    except ValueError as e:
        print(f"Error: {e}")
        temperature = 25.0  # Default temperature if missing

    return render(request, 'loading_to_prediction.html', {
        "gps_coordinates": gps_coordinates,
        "humidity": humidity,
        "temperature": temperature,
        "soil_moisture": soil_moisture,
        "crop_health": crop_health,
    })

