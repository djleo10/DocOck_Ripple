import pygame, sys, glob, os, shutil
pygame.init()
for path, subdirs, files in os.walk(r'C:\Users\Facundo\Google Drive (Ari)\Jetpack Joyride\Img1\clothing1 - backup'):
    for name in files:
        if name !='desktop.ini':
            print(name)
            nname=name
            c=0
            while os.path.isfile(nname+str(c)+'.png'):
                c+=1
                #
            nname=nname+str(c)+'.png'                
            newname=r'C:\Users\Facundo\Google Drive (Ari)\Jetpack Joyride\Img1\getlargests\\'+nname
            #print(newname)
            shutil.copyfile(os.path.join(path, name), newname)
pygame.quit()
sys.exit()
