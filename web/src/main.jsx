import React from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/mukta/latin-400.css'
import '@fontsource/mukta/latin-500.css'
import '@fontsource/mukta/latin-600.css'
import '@fontsource/mukta/latin-700.css'
import '@fontsource/b612/latin-400.css'
import '@fontsource/b612/latin-700.css'
import 'leaflet/dist/leaflet.css'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
