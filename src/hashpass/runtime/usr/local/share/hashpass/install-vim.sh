#!/bin/sh
# install-vim.sh -- удобный vim из коробки для всех пользователей системы (Debian/Ubuntu).
#
#   sudo sh install-vim.sh
#
# Ставит vim + vim-airline (строка состояния) и пишет /etc/vim/vimrc.local:
#   - русская раскладка: команды normal-режима (hjkl, dd, :wq …) работают и на русских буквах;
#     Ctrl+^ в режиме вставки переключает русский ввод внутри vim, не трогая раскладку системы;
#   - подсветка синтаксиса, номера строк, тема, строка состояния (airline) и вкладки;
#   - история: 1000 команд и поисков, отмена (u) переживает закрытие файла, курсор
#     возвращается туда, где ты закончил;
#   - Backspace/стрелки ведут себя привычно, поиск по мере набора, без учёта регистра.
# Свой ~/.vimrc этим не перекрывается: он читается после и может переопределить что угодно.
# Повторный запуск безопасен: файл настроек просто перезаписывается.
set -eu

if [ "$(id -u)" != 0 ]; then
    echo "install-vim.sh: нужен root -- запусти через sudo" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends vim vim-airline vim-airline-themes >/dev/null

mkdir -p /etc/vim
cat > /etc/vim/vimrc.local <<'VIMRC'
" vimrc.local -- общие настройки vim (install-vim.sh). Свой ~/.vimrc читается после этого файла.

" Свои настройки ниже заменяют defaults.vim (он включал mouse=a -- мышь ломала копирование).
let g:skip_defaults_vim = 1
set nocompatible

" -- кодировки: UTF-8, а старые русские файлы (cp1251, koi8-r) открываются читаемо
set encoding=utf-8
set fileencodings=ucs-bom,utf-8,cp1251,koi8-r,latin1

" -- внешний вид
syntax on
filetype plugin indent on
set background=dark
silent! colorscheme habamax
set number cursorline showcmd showmatch
set laststatus=2 ruler wildmenu wildmode=longest:full,full
set scrolloff=3 sidescrolloff=5
set display=lastline
set listchars=tab:»·,trail:·,nbsp:␣

" -- клавиши: Backspace стирает всё, стрелки переходят через край строки, Esc без задержки
set backspace=indent,eol,start
set whichwrap+=<,>,[,]
set ttimeout ttimeoutlen=50

" -- поиск: по мере набора, с подсветкой, регистр важен только если он в запросе
set incsearch hlsearch ignorecase smartcase

" -- отступы
set autoindent tabstop=4 shiftwidth=4 softtabstop=4 expandtab

" -- история: команды и поиски, отмена между запусками, место в файле
set history=1000 undolevels=1000
set viminfo='100,<500,s10,h
let s:undo = expand('~/.local/state/vim/undo')
if !isdirectory(s:undo)
    silent! call mkdir(s:undo, 'p', 0700)
endif
if isdirectory(s:undo)
    let &undodir = s:undo
    set undofile
endif
augroup hp_lastplace
    autocmd!
    autocmd BufReadPost * if line("'\"") >= 1 && line("'\"") <= line("$") && &ft !~# 'commit'
                \ | exe "normal! g`\"" | endif
augroup END

" -- русская раскладка: команды normal-режима понимают русские буквы (й=q, о=j, ш=i …)
let &langmap = 'ёйцукенгшщзхъфывапролджэячсмитьбю;`qwertyuiop[]asdfghjkl\;''zxcvbnm\,.,'
            \ . 'ЁЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ;~QWERTYUIOP{}ASDFGHJKL:"ZXCVBNM<>'
set nolangremap
" Ctrl+^ в режиме вставки -- русский ввод внутри vim (раскладку системы менять не нужно)
set keymap=russian-jcukenwin
set iminsert=0 imsearch=0
highlight lCursor guifg=NONE guibg=Cyan

" -- строка состояния: airline, если он есть, иначе простая своя
let g:airline_powerline_fonts = 0
let g:airline_theme = 'deus'
let g:airline#extensions#tabline#enabled = 1
let g:airline#extensions#keymap#enabled = 0
let g:airline_detect_iminsert = 1          " «RU» в строке -- только когда включён русский ввод
if empty(globpath(&packpath, 'pack/*/start/*/plugin/airline.vim'))
    set showmode
    set statusline=\ %f%m%r%h%w\ %=%{&fileencoding?&fileencoding:&encoding}\ \|\ %y\ \|\ %l:%c\ \|\ %p%%\
else
    set noshowmode
endif
VIMRC

echo "vim настроен: /etc/vim/vimrc.local"
