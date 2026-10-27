"""BAAS ADB tap/swipe, scaled once at the device boundary."""
class AdbControl:
    def __init__(self,conn): self.connection=conn
    def click(self,x,y,evidence=None):
        point=self.connection.coordinates.raw_point(x,y)
        self.connection.send_input(['input','tap',*map(str,point)])
        return point
    def swipe(self,x1,y1,x2,y2,duration=.3,evidence=None):
        a=self.connection.coordinates.raw_point(x1,y1)
        b=self.connection.coordinates.raw_point(x2,y2)
        self.connection.send_input(['input','swipe',*map(str,a+b),str(round(duration*1000))])
