// Towns used to describe a hexagon in plain words ("about 25 km south-west of
// Amritsar, Punjab"). City centres, rounded. Display only; not used by detection.
const P = (name, region, lat, lon) => ({ name, region, lat, lon })

export const PLACES = [
  // Punjab, Haryana, Chandigarh
  P('Amritsar', 'Punjab', 31.634, 74.872),
  P('Jalandhar', 'Punjab', 31.326, 75.576),
  P('Ludhiana', 'Punjab', 30.901, 75.857),
  P('Pathankot', 'Punjab', 32.264, 75.652),
  P('Bathinda', 'Punjab', 30.211, 74.945),
  P('Firozpur', 'Punjab', 30.925, 74.613),
  P('Patiala', 'Punjab', 30.34, 76.386),
  P('Gurdaspur', 'Punjab', 32.04, 75.403),
  P('Chandigarh', 'Chandigarh', 30.733, 76.779),
  P('Ambala', 'Haryana', 30.378, 76.776),
  P('Hisar', 'Haryana', 29.149, 75.722),
  P('Rohtak', 'Haryana', 28.895, 76.606),
  P('Panipat', 'Haryana', 29.391, 76.968),
  P('Gurugram', 'Haryana', 28.459, 77.027),
  P('Sirsa', 'Haryana', 29.534, 75.029),
  // Jammu & Kashmir, Ladakh, Himachal, Uttarakhand
  P('Jammu', 'Jammu & Kashmir', 32.727, 74.857),
  P('Srinagar', 'Jammu & Kashmir', 34.084, 74.797),
  P('Udhampur', 'Jammu & Kashmir', 32.916, 75.142),
  P('Rajouri', 'Jammu & Kashmir', 33.378, 74.31),
  P('Anantnag', 'Jammu & Kashmir', 33.73, 75.15),
  P('Baramulla', 'Jammu & Kashmir', 34.198, 74.364),
  P('Leh', 'Ladakh', 34.153, 77.577),
  P('Kargil', 'Ladakh', 34.557, 76.126),
  P('Shimla', 'Himachal Pradesh', 31.105, 77.173),
  P('Dharamshala', 'Himachal Pradesh', 32.219, 76.323),
  P('Manali', 'Himachal Pradesh', 32.24, 77.19),
  P('Dehradun', 'Uttarakhand', 30.317, 78.032),
  P('Haridwar', 'Uttarakhand', 29.945, 78.164),
  // Delhi, Uttar Pradesh
  P('Delhi', 'Delhi', 28.614, 77.209),
  P('Noida', 'Uttar Pradesh', 28.535, 77.391),
  P('Meerut', 'Uttar Pradesh', 28.984, 77.706),
  P('Agra', 'Uttar Pradesh', 27.177, 78.008),
  P('Aligarh', 'Uttar Pradesh', 27.897, 78.088),
  P('Mathura', 'Uttar Pradesh', 27.492, 77.674),
  P('Bareilly', 'Uttar Pradesh', 28.367, 79.432),
  P('Moradabad', 'Uttar Pradesh', 28.839, 78.773),
  P('Lucknow', 'Uttar Pradesh', 26.847, 80.947),
  P('Kanpur', 'Uttar Pradesh', 26.449, 80.331),
  P('Varanasi', 'Uttar Pradesh', 25.317, 82.973),
  P('Prayagraj', 'Uttar Pradesh', 25.435, 81.846),
  P('Gorakhpur', 'Uttar Pradesh', 26.76, 83.373),
  // Rajasthan, Gujarat, Madhya Pradesh
  P('Jaipur', 'Rajasthan', 26.912, 75.787),
  P('Jodhpur', 'Rajasthan', 26.238, 73.024),
  P('Bikaner', 'Rajasthan', 28.022, 73.312),
  P('Sri Ganganagar', 'Rajasthan', 29.904, 73.877),
  P('Jaisalmer', 'Rajasthan', 26.915, 70.908),
  P('Barmer', 'Rajasthan', 25.746, 71.393),
  P('Ajmer', 'Rajasthan', 26.449, 74.639),
  P('Alwar', 'Rajasthan', 27.553, 76.635),
  P('Udaipur', 'Rajasthan', 24.585, 73.712),
  P('Kota', 'Rajasthan', 25.213, 75.865),
  P('Churu', 'Rajasthan', 28.304, 74.967),
  P('Gwalior', 'Madhya Pradesh', 26.218, 78.183),
  P('Bhopal', 'Madhya Pradesh', 23.259, 77.413),
  P('Indore', 'Madhya Pradesh', 22.72, 75.858),
  P('Ahmedabad', 'Gujarat', 23.023, 72.571),
  P('Bhuj', 'Gujarat', 23.242, 69.666),
  // Elsewhere in India
  P('Mumbai', 'Maharashtra', 19.076, 72.878),
  P('Patna', 'Bihar', 25.594, 85.137),
  P('Kolkata', 'West Bengal', 22.573, 88.364),
  P('Hyderabad', 'Telangana', 17.385, 78.487),
  P('Bengaluru', 'Karnataka', 12.972, 77.595),
  P('Chennai', 'Tamil Nadu', 13.083, 80.271),
  // Neighbours
  P('Lahore', 'Pakistan', 31.52, 74.359),
  P('Islamabad', 'Pakistan', 33.684, 73.048),
  P('Sialkot', 'Pakistan', 32.494, 74.531),
  P('Gujranwala', 'Pakistan', 32.188, 74.194),
  P('Faisalabad', 'Pakistan', 31.418, 73.079),
  P('Multan', 'Pakistan', 30.198, 71.469),
  P('Bahawalpur', 'Pakistan', 29.395, 71.683),
  P('Peshawar', 'Pakistan', 34.015, 71.525),
  P('Karachi', 'Pakistan', 24.861, 67.01),
  P('Kathmandu', 'Nepal', 27.717, 85.324),
]

const COMPASS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']

/** "about 25 km south-west of Amritsar, Punjab" for a point. */
export function describePlace(lat, lon, haversineKm, bearingDeg) {
  let best = null
  for (const p of PLACES) {
    const km = haversineKm(p.lat, p.lon, lat, lon)
    if (!best || km < best.km) best = { ...p, km }
  }
  if (!best) return null
  const where = `${best.name}, ${best.region}`
  if (best.km < 15) return { ...best, short: `over ${best.name}`, text: `right over ${where}` }
  const dir = COMPASS[Math.round(bearingDeg(best.lat, best.lon, lat, lon) / 45) % 8]
  const km = best.km < 100 ? Math.round(best.km / 5) * 5 : Math.round(best.km / 10) * 10
  return { ...best, dir, short: `${km} km ${dir} of ${best.name}`, text: `about ${km} km ${dir} of ${where}` }
}
