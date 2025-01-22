import os
import math
import random
import numpy as np
from PIL import Image
from io import BytesIO
from django.conf import settings
import requests
from django.shortcuts import render, redirect
from sentinelhub import (
    SHConfig,
    DataCollection,
    SentinelHubRequest,
    BBox,
    bbox_to_dimensions,
    CRS,
    MimeType,
)

# Sentinel Hub configuration
config = SHConfig()
config.sh_client_id = "sh-d9535a06-2e21-4cc2-b14f-8ce7e2ce44f4"
config.sh_client_secret = "ztSgqnCYZ9fnNoS1fQdCHX7O0MVSLTIx"
config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
config.sh_base_url = "https://sh.dataspace.copernicus.eu"
config.save("cdse")

# Helper function to calculate bounding box
def calculate_bbox(latitude, longitude, radius):
    radius_in_degrees = radius / 110_567  # Convert meters to degrees
    lon_scaling = math.cos(math.radians(latitude))
    lon_offset = radius_in_degrees / lon_scaling
    return [
        longitude - lon_offset,
        latitude - radius_in_degrees,
        longitude + lon_offset,
        latitude + radius_in_degrees,
    ]
# Function to process NDVI
def process_ndvi(latitude, longitude, radius, save_path="agriculture/static/images/ndvi_output.png"):
    aoi_coords_wgs84 = calculate_bbox(latitude, longitude, radius)
    resolution = 10
    aoi_bbox = BBox(bbox=aoi_coords_wgs84, crs=CRS.WGS84)
    aoi_size = bbox_to_dimensions(aoi_bbox, resolution=resolution)

    evalscript_ndvi = """
    //VERSION=3
    function setup() {
      return {
        input: [ {
          bands: ["B04", "B08", "dataMask"]
        }],
        output: { bands: 4 }
      };
    }

    function evaluatePixel(sample) {
        let val = (sample.B08 - sample.B04) / (sample.B08 + sample.B04);
        let imgVals = null;

        if (val < 0.05) imgVals = [0, 0, 0];  // Bad vegetation
        else if (val < 0.15) imgVals = [0, 128, 0];  // Poor vegetation
        else if (val < 0.3) imgVals = [128, 255, 0];  // Average vegetation
        else if (val < 0.5) imgVals = [255, 255, 0];  // Good vegetation
        else imgVals = [0, 255, 0];  // Excellent vegetation

        imgVals.push(sample.dataMask);
        return imgVals;
    }
    """

    request_ndvi_img = SentinelHubRequest(
        evalscript=evalscript_ndvi,
        input_data=[
            SentinelHubRequest.input_data(
                data_collection=DataCollection.SENTINEL2_L2A.define_from(
                    name="s2l2a", service_url="https://sh.dataspace.copernicus.eu"
                ),
                time_interval=("2024-12-01", "2024-12-30"),
                other_args={"dataFilter": {"mosaickingOrder": "leastCC"}},
            )
        ],
        responses=[SentinelHubRequest.output_response("default", MimeType.PNG)],
        bbox=aoi_bbox,
        size=aoi_size,
        config=config,
    )

    ndvi_img = request_ndvi_img.get_data()
    image = ndvi_img[0]

    # Save the NDVI image
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    ndvi_image = Image.fromarray(image)
    ndvi_image.save(save_path)
    return save_path
# Function to fetch weather data
def fetch_weather_data(latitude, longitude):
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
    return current_weather
# Function to crop satellite image
def process_satellite_image(latitude, longitude, radius, save_path):
    """
    Processes and saves a cropped satellite image based on latitude, longitude, and radius.
    """
    # Generate a URL for the satellite image
    satellite_url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox={longitude - 0.01},{latitude - 0.01},{longitude + 0.01},{latitude + 0.01}&bboxSR=4326&size=800,800&imageSR=4326&format=png&f=image"

    response = requests.get(satellite_url, stream=True)
    if response.status_code == 200:
        with open(save_path, "wb") as f:
            f.write(response.content)
    else:
        print(f"Error fetching satellite image: {response.status_code}")
# Function to calculate vegetation percentage
def calculate_overall_vegetation_quality(ndvi_image_path, black_penalty=0.0):
    ndvi_image = Image.open(ndvi_image_path)
    ndvi_array = np.array(ndvi_image)

    # Create masks for each category
    green_mask = (ndvi_array[:, :, 0] == 0) & (ndvi_array[:, :, 1] == 255) & (ndvi_array[:, :, 2] == 0)
    yellow_mask = (ndvi_array[:, :, 0] == 255) & (ndvi_array[:, :, 1] == 255) & (ndvi_array[:, :, 2] == 0)
    black_mask = (ndvi_array[:, :, 0] == 0) & (ndvi_array[:, :, 1] == 0) & (ndvi_array[:, :, 2] == 0)

    # Count pixels for each category
    green_pixels = np.sum(green_mask)
    yellow_pixels = np.sum(yellow_mask)
    black_pixels = np.sum(black_mask)

    # Total pixels
    total_pixels = ndvi_array.shape[0] * ndvi_array.shape[1]

    # Debug: Print counts
    print(f"Green pixels: {green_pixels}, Yellow pixels: {yellow_pixels}, Black pixels: {black_pixels}, Total pixels: {total_pixels}")

    # Calculate weighted average quality percentage
    quality_percentage = (
        (green_pixels * 1.0 + yellow_pixels * 0.5 + black_pixels * black_penalty) / total_pixels
    ) * 100

    # Return rounded quality percentage
    return round(quality_percentage, 2)
def result(request):
    gps_coordinates = request.GET.get("gps_coordinates")
    radius = request.GET.get("radius")

    # Validate inputs
    if not gps_coordinates or not radius:
        return redirect("/")  # Redirect to home page if parameters are missing

    # Parse latitude and longitude
    try:
        latitude, longitude = map(float, gps_coordinates.split(","))
        radius = float(radius)
    except ValueError:
        return redirect("/")  # Redirect to home page if parameters are invalid

    # Paths for images
    ndvi_save_path = os.path.join(settings.MEDIA_ROOT, "ndvi_output.png")
    cropped_image_path = os.path.join(settings.MEDIA_ROOT, "satellite_cropped.png")

    # Process NDVI and satellite cropped images
    process_ndvi(latitude, longitude, radius, ndvi_save_path)
    process_satellite_image(latitude, longitude, radius, cropped_image_path)

    # Fetch weather data
    weather_data = fetch_weather_data(latitude, longitude)

    # Calculate vegetation percentages
    vegetation_quality_percentage = calculate_overall_vegetation_quality(ndvi_save_path, black_penalty=-0.2)

    # Generate random environmental stats
    crop_health = "Good" if vegetation_quality_percentage >= 50 else "Average"
    humidity = random.randint(60, 90)  # Simulated
    soil_moisture = random.randint(20, 80)  # Simulated
    wind_speed = round(random.uniform(5, 20), 1)  # Simulated
    fertilizer_usage = random.choice(["Low", "Moderate", "High"])  # Simulated

    # Pass data to the template
    return render(request, "result.html", {
        "gps_coordinates": gps_coordinates,
        "radius": radius,
        "ndvi_image_path": settings.MEDIA_URL + "ndvi_output.png",
        "satellite_image_path": settings.MEDIA_URL + "satellite_cropped.png",
        "vegetation_quality_percentage": vegetation_quality_percentage,
        "crop_health": crop_health,
        "humidity": humidity,
        "soil_moisture": soil_moisture,
        "wind_speed": wind_speed,
        "fertilizer_usage": fertilizer_usage,
        "current_weather": weather_data,
    })
# Home Page View
def home(request):
    return render(request, "home.html")
# Loading Page View
def home_to_loading(request):
    gps_coordinates = request.GET.get("gps_coordinates")
    radius = request.GET.get("radius")
    return render(request, 'loading_to_results.html', {
        "gps_coordinates": gps_coordinates,
        "radius": radius,
    })
# Results to Loading View
def results_to_loading(request):
    gps_coordinates = request.GET.get("gps_coordinates")
    humidity = request.GET.get("humidity")
    temperature = request.GET.get("temperature")
    soil_moisture = request.GET.get("soil_moisture")
    crop_health = request.GET.get("crop_health")

    try:
        if not temperature or temperature == '':
            raise ValueError("Temperature value is missing.")
        temperature = float(temperature)
    except ValueError as e:
        print(f"Error: {e}")
        temperature = 25.0

    return render(request, 'loading_to_prediction.html', {
        "gps_coordinates": gps_coordinates,
        "humidity": humidity,
        "temperature": temperature,
        "soil_moisture": soil_moisture,
        "crop_health": crop_health,
    })
def prediction_model(request):
    # Fetch parameters from the request
    humidity = int(request.GET.get("humidity", 0))
    temperature = float(request.GET.get("temperature", 0))
    soil_moisture = int(request.GET.get("soil_moisture", 0))
    crop_health = request.GET.get("crop_health", "Good")

    # Default prediction and confidence
    prediction = "No Outbreak Likely"
    confidence = random.uniform(90, 99)  # High confidence for safe conditions

    # Prediction logic based on environmental stats
    if humidity > 85 and temperature > 35 and soil_moisture < 20 and crop_health == "Poor":
        prediction = "Extensive Outbreak"
        confidence = random.uniform(80, 90)
    elif (
        (75 < humidity <= 85) or
        (30 < temperature <= 35) or
        (20 <= soil_moisture < 30) or
        crop_health == "Average"
    ):
        prediction = "Possible Outbreak"
        confidence = random.uniform(75, 85)
    elif (
        (60 < humidity <= 75) or
        (25 < temperature <= 30) or
        (30 <= soil_moisture <= 50)
    ):
        prediction = "No Outbreak Possible"
        confidence = random.uniform(85, 95)

    # Pass the prediction and confidence to the template
    return render(request, 'prediction.html', {
        "prediction": prediction,
        "confidence": round(confidence, 2),  # Round confidence to 2 decimal places
    })
