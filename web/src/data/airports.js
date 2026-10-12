// Reference aerodromes drawn on the outline map (ICAO code, city, lat, lon).
// They orient the viewer when no map tiles are loaded; they are not used by detection.
export const AIRPORTS = [
  ['VIDP', 'Delhi', 28.5665, 77.1031],
  ['VIAR', 'Amritsar', 31.7096, 74.7973],
  ['VIJU', 'Jammu', 32.6891, 74.8374],
  ['VISR', 'Srinagar', 33.9871, 74.7742],
  ['VILH', 'Leh', 34.1359, 77.5465],
  ['VICG', 'Chandigarh', 30.6735, 76.7885],
  ['VIDN', 'Dehradun', 30.1897, 78.1803],
  ['VIJP', 'Jaipur', 26.8242, 75.8122],
  ['VIJO', 'Jodhpur', 26.2511, 73.0489],
  ['VIAG', 'Agra', 27.1558, 77.9609],
  ['VILK', 'Lucknow', 26.7606, 80.8893],
  ['VIBN', 'Varanasi', 25.4524, 82.8593],
  ['VEPT', 'Patna', 25.5913, 85.088],
  ['VAAH', 'Ahmedabad', 23.0772, 72.6347],
  ['VABB', 'Mumbai', 19.0887, 72.8679],
  ['VOHS', 'Hyderabad', 17.2403, 78.4294],
  ['VOBL', 'Bengaluru', 13.1979, 77.7063],
  ['VOMM', 'Chennai', 12.9941, 80.1709],
  ['VECC', 'Kolkata', 22.6547, 88.4467],
  ['OPIS', 'Islamabad', 33.5491, 72.8256],
  ['OPLA', 'Lahore', 31.5216, 74.4036],
  ['OPPS', 'Peshawar', 33.9939, 71.5146],
  ['OPMT', 'Multan', 30.2033, 71.4191],
  ['OPKC', 'Karachi', 24.9065, 67.1608],
  ['VNKT', 'Kathmandu', 27.6966, 85.3591],
].map(([icao, city, lat, lon]) => ({ icao, city, lat, lon }))

export function nearestAirport(lat, lon, haversineKm) {
  let best = null
  for (const a of AIRPORTS) {
    const d = haversineKm(lat, lon, a.lat, a.lon)
    if (!best || d < best.km) best = { ...a, km: d }
  }
  return best
}
