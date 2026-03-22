'use client';

import React, { useCallback, useRef, useState } from 'react';
import { FileUp } from 'lucide-react';

interface DropzoneProps {
  accept?: string;
  multiple?: boolean;
  label: string;
  onFiles: (files: FileList) => void;
}

export default function Dropzone({ accept = '.pdf', multiple = false, label, onFiles }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files);
    },
    [onFiles]
  );

  return (
    <div
      className={`
        relative flex flex-col items-center justify-center gap-3 p-8 rounded-xl cursor-pointer
        border-2 border-dashed transition-all duration-300
        ${dragOver
          ? 'border-accent bg-accent-glow scale-[1.01]'
          : 'border-border hover:border-border-hover hover:bg-bg-hover/50'
        }
      `}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={(e) => e.target.files && onFiles(e.target.files)}
      />
      <div className="w-10 h-10 rounded-lg bg-bg-hover flex items-center justify-center">
        <FileUp className="w-5 h-5 text-text-muted" strokeWidth={1.75} />
      </div>
      <p className="text-sm text-text-secondary text-center">
        {label} or <span className="text-accent font-medium">click to browse</span>
      </p>
    </div>
  );
}
