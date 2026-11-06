;; Shared helpers for Phase 0 probes. *dir* is set by the bootstrap.
(vl-load-com)

(defun log-kv (k v / f)
  (setq f (open (strcat *dir* "log.txt") "a"))
  (write-line (strcat (rtos (getvar "CDATE") 2 6) " " k " = " (vl-prin1-to-string v)) f)
  (close f)
)

(defun safe (k fn / r)
  (setq r (vl-catch-all-apply fn nil))
  (log-kv k (if (vl-catch-all-error-p r)
              (strcat "ERROR: " (vl-catch-all-error-message r))
              r))
  r
)

(defun state ()
  (list (getvar "DWGNAME") (getvar "DBMOD") (getvar "CMDACTIVE") (getvar "CMDNAMES") (getvar "LASTPROMPT"))
)

(defun add-line ()
  (entmakex (list '(0 . "LINE") '(10 0.0 0.0 0.0) '(11 100.0 100.0 0.0)))
)

(defun finish ()
  (log-kv "done" T)
  (command "_.QUIT" "_Y")
  (princ)
)
