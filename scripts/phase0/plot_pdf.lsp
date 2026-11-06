;; Q: can a PDF be written with no dialog? Logs every prompt in the -PLOT sequence.
(log-kv "commands"
  (mapcar (function (lambda (c) (cons c (getcname c))))
          '("PLOT" "-PLOT" "PRINT" "EXPORT" "-EXPORT" "PDFEXPORT" "-PDFEXPORT" "EXPORTPDF"
            "-EXPORTPDF" "PUBLISH" "-PUBLISH" "PNGOUT" "JPGOUT" "BMPOUT" "DXFOUT")))
(entmakex (list '(0 . "LINE") '(10 0.0 0.0 0.0) '(11 200.0 100.0 0.0)))
(command "_.SAVEAS" "" (strcat *dir* "plot.dwg"))

(defun feed (answers)
  (foreach a answers
    (if (> (getvar "CMDACTIVE") 0)
      (progn
        (log-kv "prompt" (getvar "LASTPROMPT"))
        (log-kv "answer" a)
        (command a)
      )
    )
  )
  (log-kv "feed-end" (list (getvar "CMDACTIVE") (getvar "LASTPROMPT")))
)

(command "_.-PLOT")
(feed *answers*)
(if (> (getvar "CMDACTIVE") 0) (command))
(log-kv "pdf-exists" (findfile (strcat *dir* "out.pdf")))
(if (findfile (strcat *dir* "out.pdf"))
  (log-kv "pdf-size" (vl-file-size (strcat *dir* "out.pdf"))))
(finish)
