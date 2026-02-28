# 🧪 Nitrate–Cancer Spatial Analysis App

🔗 **Live Demo:**  
https://chadlanoway.github.io/nitrate-cancer-spatial-analysis/

---

## 📖 Overview

An interactive web GIS application exploring the relationship between well water nitrate concentrations and census tract–level cancer incidence rates.

The app:

- Interpolates scattered well nitrate samples using **Inverse Distance Weighting (IDW)**
- Aggregates interpolated values to census tracts
- Runs **linear regression**
- Visualizes results through interactive map layers and a scatter plot
- Allows export of a downloadable ZIP report

---

## 🔎 Features

### 🌊 1. IDW Interpolation
- Converts point-based well nitrate measurements into a continuous raster
- Adjustable distance decay parameter `k`
- 500m raster resolution
- 32 nearest wells per pixel

### 🗺 2. Census Tract Aggregation
- Computes mean nitrate per tract
- Merges predicted and residual values into tract GeoJSON

### 📈 3. Regression Analysis
Model:

```
canrate ~ mean_nitrate
```

Returns:
- Slope
- p-value
- R²
- Predicted values
- Residuals

### 🎛 Interactive Layers
- Cancer rate choropleth
- Nitrate raster (IDW)
- Residual choropleth
- Toggleable layers with synced legends
- Hover tooltips (residual-focused)

### 📊 Scatter Plot Modal
- Mean nitrate vs observed canrate
- Regression line overlay
- Canvas-rendered
- Exportable as PNG

### 📦 Downloadable ZIP Report
Includes:
- HTML summary
- Regression JSON
- Residual CSV
- Scatter PNG

---

## 🏗 Architecture

### Frontend
- **Vite**
- **MapLibre GL JS**
- Modular UI panel
- Canvas-based scatter plot
- Hosted on GitHub Pages

### Backend
- **Flask API**
- Flask-Compress
- Flask-CORS
- S3-backed cache system
- Deployed on AWS App Runner

### Storage
- S3 bucket: `cancer-nitrate-app-cache`
- Cached artifacts:

```
cache/
  meta/
  png/
  tables/
  results/
```

---

## 📡 API Endpoints

| Endpoint | Description |
|-----------|------------|
| `/api/health` | Health check |
| `/api/tracts` | Returns tract GeoJSON with nitrate + residual fields |
| `/api/idw_meta` | Returns IDW image metadata |
| `/api/idw.png` | Returns colorized nitrate PNG |
| `/api/regression` | Returns regression JSON |
| `/api/report.zip` | Returns downloadable ZIP report |

---

## ⚙ Parameters

| Parameter | Meaning |
|------------|---------|
| `k` | IDW distance decay exponent |
| `cell` | Raster cell size (meters) |
| `knn` | Number of nearest wells per pixel |

Example request:

```
/api/tracts?k=2&cell=500&knn=32
```

---

## 🧠 Interpretation Notes

- Higher `k` → more localized interpolation
- Lower `k` → smoother surface
- R² = proportion of variance explained
- p-value tests slope significance
- Residual = observed − predicted cancer rate

---

## 🛠 Local Development

### Backend

```
python app.py
```

Or Docker:

```
docker build -t nitrate-backend .
docker run -p 8000:8000 nitrate-backend
```

### Frontend

```
npm install
npm run dev
```

Set environment variable:

```
VITE_API_BASE=http://localhost:8000
```

---

## 📁 Project Structure

```
frontend/
  main.js
  ui-panel.js
  style.css

backend/
  app.py
  src/
    pipeline.py
    idw_preview.py
    load_data.py
    make_web_tracts.py
    regression_preview.py
    tract_nitrate_table.py
    warm_idw_cache.py
  cache/
```

---

## 🚀 Future Improvements

- Multiple regression models
- Spatial autocorrelation testing
- Model comparison panel
- PDF report export
- Animated k-value comparison

---

## 📜 License

MIT
