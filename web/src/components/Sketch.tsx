import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Icon } from "./ui";

// What is in a file: a 2D drawing's plan (SVG, inlined so it follows the theme's colours) or an
// IFC's building rendered in 3D (PNG). Drawn by the server, see backend compliance/thumbnail.py.
type Pic = { svg: string } | { png: string };

export default function Sketch({ src, className = "" }: { src: string; className?: string }) {
  const q = useQuery({
    queryKey: ["sketch", src],
    queryFn: async (): Promise<Pic> => {
      const r = await fetch(src);
      if (!r.ok) throw new Error("no thumbnail");
      if ((r.headers.get("content-type") ?? "").includes("svg") || src.endsWith(".svg")) {
        const t = await r.text();
        if (!t.startsWith("<svg")) throw new Error("no thumbnail");
        return { svg: t };
      }
      return { png: URL.createObjectURL(await r.blob()) };
    },
    retry: false,
    staleTime: 60_000,
  });
  const png = q.data && "png" in q.data ? q.data.png : null;
  useEffect(() => () => void (png && URL.revokeObjectURL(png)), [png]);

  if (q.data && "svg" in q.data)
    return <div className={`[&>svg]:h-full [&>svg]:w-full ${className}`} aria-hidden dangerouslySetInnerHTML={{ __html: q.data.svg }} />;
  if (png)
    return (
      <div className={className} aria-hidden>
        <img src={png} alt="" className="h-full w-full object-contain" />
      </div>
    );
  return (
    <div className={`grid place-items-center text-fg-off ${className}`} aria-hidden>
      {q.isLoading ? <span className="h-2/3 w-2/3 animate-pulse rounded-sm bg-surface-raised" /> : <Icon name="cube" size={28} />}
    </div>
  );
}
