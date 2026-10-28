import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const PUNE = { lat: 18.5204, lon: 73.8567 };

export interface LatLon {
  lat: number;
  lon: number;
}

// Dark grayscale basemap, a fixed mono coordinate/zoom readout and a north arrow.
// Click the map to place or move the pin.
export default function MapPin({
  value,
  onChange,
  center = PUNE,
  className = "h-80",
}: {
  value: LatLon | null;
  onChange: (v: LatLon) => void;
  center?: LatLon;
  className?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const cb = useRef(onChange);
  cb.current = onChange;
  const [zoom, setZoom] = useState(value ? 16 : 12);
  const [cursor, setCursor] = useState<LatLon | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const start = value ?? center;
    const m = L.map(host.current, { attributionControl: true }).setView([start.lat, start.lon], value ? 16 : 12);
    // Standard OSM tiles (no key), turned into a dark grayscale basemap by CSS (.map-dark in index.css).
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      className: "map-dark",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => cb.current({ lat: +e.latlng.lat.toFixed(6), lon: +e.latlng.lng.toFixed(6) }));
    m.on("zoomend", () => setZoom(m.getZoom()));
    m.on("mousemove", (e: L.LeafletMouseEvent) => setCursor({ lat: e.latlng.lat, lon: e.latlng.lng }));
    m.on("mouseout", () => setCursor(null));
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      marker.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !value) return;
    const ll: [number, number] = [value.lat, value.lon];
    if (marker.current) marker.current.setLatLng(ll);
    else
      marker.current = L.circleMarker(ll, {
        radius: 7,
        color: getComputedStyle(document.documentElement).getPropertyValue("--text-primary").trim() || "#f2f2f3",
        weight: 2.5,
        fillColor: "#d22b10",
        fillOpacity: 1,
      }).addTo(m);
    if (!m.getBounds().pad(-0.2).contains(ll)) m.setView(ll, Math.max(m.getZoom(), 16));
  }, [value]);

  const shown = cursor ?? value;
  return (
    <div className={`relative overflow-hidden rounded-md border border-line-subtle ${className}`}>
      <div ref={host} className="absolute inset-0" />
      <div className="pointer-events-none absolute right-3 top-3 z-[500] flex flex-col items-center rounded-sm border border-line-subtle bg-surface px-1.5 py-1 text-fg-2">
        <svg width="12" height="16" viewBox="0 0 12 16" fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden>
          <path d="M6 1l4 13-4-3-4 3 4-13z" />
        </svg>
        <span className="font-mono text-2xs leading-3">N</span>
      </div>
      <div className="readout pointer-events-none absolute bottom-3 left-3 z-[500]">
        {shown ? `${shown.lat.toFixed(5)}° N  ${shown.lon.toFixed(5)}° E` : "—"}  ·  z{zoom}
      </div>
    </div>
  );
}
