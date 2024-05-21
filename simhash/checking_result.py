import sys
from simhash_base import get_simhash   

way_to_answer=r'/home/lev/hashpass/simhash' #?#
stage=1 #!#
def check_result(result):
    global stage
    #print(result,way_to_answer+r"/"+str(stage))
    data_1 = get_simhash(result)
    data_2 = get_simhash(way_to_answer+r"/"+str(stage))
    if data_1.distance(data_2) <= 10:
        stage += 1
        if stage == 2:
            print("Done")
            sys.exit()
            # если результат достиг этапа, то ...
