# 21.07.2015

Дана версія програми встановлюєтсья на OS Ubuntu Linux (14.04).

Архів з програмою потрібно розпакувати в '~/projects/Predator' або, якщо в іншу папку - пофіксати шляхи в uav.desktop  і скопіювати його в '~/Desktop/', якщо потрібно запускати з ярлика з мінімальним логуванням. 

Для адекватного функціонування програми потрібно встановити Python (2.7) з такими бібліотеками:
(в дужках вказані рекомендовані версії)
- cairo (1.8.8);
- Gdk, Gtk (GTK + 3), GObject (біндінги);

Також в системі потрібно встановити:
- VLC media player 2.1.6 Rincewind or later;
- OpenCV 3.0.0 with Python Bindings (https://github.com/Itseez/opencv);
- caffe with Python Bindings (https://github.com/BVLC/caffe);


Після встановлення/білдання всіх необхідних бібліотек потрібно залінкувати програму з caffe:
cd ~/шлях_до_програми
sudo ln -s шлях_до_каталогу_з_(_caffe.so, ex. caffe/distribute/python/caffe) ./caffe

Дати права на виконання файлу gtk3vlc.py ("sudo chmod 754 gtk3vlc.py")

Можна запускати з терміналу ("~/projects/Predator$ python gtk3vlc.py") або ярлика.
Terminal=false в uav.desktop для запуску без відображення терміналу.
stdout пишеться в ~/uav_launch.log (на випадок крешів).

Вимоги до апаратної частини:
- Intel i7 Processor;
- RAM > 8 Gb;
- Graphic adapter: NVIDIA Quadro K1100M (Kepler) або краще (відеоадаптер повинен підтримувати CUDA, підтримка cuDNN є бажаною);


Програма вимагає рефакторингу і, можливо, оптимізації - над чим і працюватиму у вільний час.
Приємного користування.
