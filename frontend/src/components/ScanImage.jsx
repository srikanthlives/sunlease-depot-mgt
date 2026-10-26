import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import client from "../api/client";

/**
 * A scanned page image from the API.
 *
 * The API is behind a bearer token, which a plain <img src> cannot send, so the picture is fetched
 * the same way as any other call and shown from an object URL. `onUrl` hands that URL back, so a
 * caller can offer "open full size" without fetching the page twice.
 */
export default function ScanImage({ path, alt, className, onUrl }) {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let made = null;
    setUrl(null);
    setFailed(false);
    client.get(path, { responseType: "blob" })
      .then((r) => {
        if (!live) return;
        made = URL.createObjectURL(r.data);
        setUrl(made);
        onUrl?.(made);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [path]);                                  // eslint-disable-line react-hooks/exhaustive-deps

  if (failed) return <p className="p-6 text-center text-sm text-slate-500">This page image is no longer on the server.</p>;
  if (!url) return <p className="flex items-center justify-center gap-2 p-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> loading the page…</p>;
  return <img alt={alt} src={url} className={className} />;
}
