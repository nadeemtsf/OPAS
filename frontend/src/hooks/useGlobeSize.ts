import { useEffect, useRef, useState } from "react";

export function useGlobeSize() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [globeSize, setGlobeSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    function updateSize() {
      if (containerRef.current) {
        setGlobeSize({ w: containerRef.current.clientWidth, h: containerRef.current.clientHeight });
      }
    }
    updateSize();
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  return { containerRef, globeSize };
}
