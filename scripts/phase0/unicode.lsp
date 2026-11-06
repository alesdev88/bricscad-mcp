;; Q: do non-ASCII characters survive LISP source, files, names and paths?
(setq *s* "čšžČŠŽ")
(log-kv "strlen-should-be-6" (strlen *s*))
(log-kv "codes" (vl-string->list *s*))

;; Writing files: default mode and explicit encodings.
(defun try-write (name args / f)
  (setq f (apply 'open (append (list (strcat *dir* name) "w") args)))
  (write-line *s* f)
  (close f)
  T
)
(safe "write-default" (function (lambda () (try-write "default.raw" nil))))
(safe "write-utf8" (function (lambda () (try-write "utf8.raw" '("utf8")))))
(safe "write-ccs" (function (lambda () (try-write "ccs.raw" '("ccs=UTF-8")))))

;; Reading a UTF-8 file made outside BricsCAD.
(defun try-read (args / f r)
  (setq f (apply 'open (append (list (strcat *here* "unicode_input.txt") "r") args)))
  (setq r (read-line f))
  (close f)
  (list r (strlen r))
)
(safe "read-default" (function (lambda () (try-read nil))))
(safe "read-utf8" (function (lambda () (try-read '("utf8")))))
(safe "file-encoding"
  (function (lambda () (vle-file-encoding (strcat *here* "unicode_input.txt")))))

;; Names and text inside the drawing.
(safe "layer" (function (lambda ()
  (command "_.-LAYER" "_N" "Načrt-čšž" "")
  (cdr (assoc 2 (tblsearch "LAYER" "Načrt-čšž"))))))
(safe "text" (function (lambda (/ e)
  (setq e (entmakex (list '(0 . "TEXT") '(10 0.0 0.0 0.0) '(40 . 2.5) (cons 1 *s*))))
  (list (cdr (assoc 1 (entget e))) (strlen (cdr (assoc 1 (entget e))))))))

;; Paths.
(safe "saveas-path" (function (lambda ()
  (command "_.SAVEAS" "" (strcat *dir* "Načrt št 1.dwg"))
  (list (getvar "DWGNAME") (strlen (getvar "DWGNAME"))))))
(log-kv "path-found" (findfile (strcat *dir* "Načrt št 1.dwg")))
(finish)
