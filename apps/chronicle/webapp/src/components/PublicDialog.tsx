import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "../styles/public-reading.css";

/** One native dialog for public reading tools; dismissal preserves the reading position. */
export default function PublicDialog({ title, children, onClose, compact = false, closeTestId }: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  compact?: boolean;
  closeTestId?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const origin = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
      if (origin?.isConnected) origin.focus({ preventScroll: true });
    };
  }, []);
  const content = (
    <dialog
      ref={ref}
      className={`public-dialog${compact ? " public-dialog-compact" : ""}`}
      aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
      }}
    >
      <header className="public-dialog-heading"><h2 id={titleId}>{title}</h2><button type="button" className="public-icon-button" aria-label="关闭面板" data-test={closeTestId} onClick={onClose}>×</button></header>
      <div className="public-dialog-content">{children}</div>
    </dialog>
  );
  return typeof document === "undefined" ? content : createPortal(content, document.body);
}
