import { useEffect, useState } from 'react'

import { apiBlob } from '../../lib/http'

export function AuthedMedia({
  path,
  alt,
  className,
}: {
  path: string
  alt: string
  className?: string
}) {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setUrl(null)
    void apiBlob(path)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => undefined)
    return () => {
      active = false
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl)
    }
  }, [path])

  if (url === null) {
    return <div className={`animate-pulse bg-surface-muted ${className ?? ''}`} />
  }
  return <img src={url} alt={alt} className={className} />
}