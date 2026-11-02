import { useCallback, useEffect, useState } from "react";
import client, { apiErrorMessage } from "../api/client";

/** GET `url` (null = skip). Returns {data, loading, error, reload}. */
export function useApi(url, initial = null) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(!!url);
  const [error, setError] = useState(null);
  const reload = useCallback(async () => {
    if (!url) return;
    setLoading(true);
    try {
      const r = await client.get(url);
      setData(r.data);
      setError(null);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [url]);
  useEffect(() => { reload(); }, [reload]);
  return { data, loading, error, reload, setData };
}

export const locOptions = (locs, filter = () => true) =>
  (locs || []).filter((l) => l.is_active && filter(l)).map((l) => ({ value: l.location_id, label: l.location_name, sub: l.location_code }));
