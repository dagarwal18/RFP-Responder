'use client';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Download, ExternalLink } from 'lucide-react';

interface DocumentPreviewModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  downloadUrl: string;
  filename: string;
}

export default function DocumentPreviewModal({
  open,
  onOpenChange,
  downloadUrl,
  filename,
}: DocumentPreviewModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Document Preview</DialogTitle>
          <DialogDescription>
            Previewing the generated response for{' '}
            <span className="font-medium text-foreground">{filename}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 rounded-lg overflow-hidden border border-border bg-muted/20">
          <iframe
            src={downloadUrl}
            title="Document Preview"
            className="w-full h-full"
            style={{ border: 'none' }}
          />
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => window.open(downloadUrl, '_blank')}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Open in New Tab
          </Button>
          <a href={downloadUrl} download>
            <Button>
              <Download className="mr-2 h-4 w-4" />
              Download
            </Button>
          </a>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
